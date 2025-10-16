"""
LSAC Status Checker - Open Source
Simple law school application status checker with change detection

Setup:
1. pip install playwright requests python-dotenv
2. playwright install chromium
3. Create .env file with your LSAC credentials
4. Create schools.txt with one status checker link per line
5. Run: python lsac_checker.py

Features:
- Automatic change detection (status updates, checklist progress)
- Saves history to status_history.json
- Shows 🚨 alerts when something changes
"""

import json
import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright
import requests
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()


class LSACChecker:
    def __init__(self):
        self.subscription_key = 'b2acf0d4d39d47bb8405b947e0282a04'
        self.api_base_url = 'https://aces-prod-apimgmt.azure-api.net/aso/api/v1'
        self.token = None
        self.guid = None
    
    def load_schools_from_file(self, filename='schools.txt'):
        """
        Load school status checker links from file and extract GUIDs
        
        Format options in schools.txt:
        
        Option 1 - Just the link:
        https://aso.lsac-unite.org/?guid=xjQd2C0H4WM%3d
        
        Option 2 - School name, then link:
        Harvard Law School
        https://aso.lsac-unite.org/?guid=abc123
        
        Option 3 - School name with pipe separator:
        Yale Law School | https://aso.lsac-unite.org/?guid=def456
        """
        schools = {}
        
        try:
            with open(filename, 'r') as f:
                lines = f.readlines()
            
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    i += 1
                    continue
                
                school_name = None
                link = None
                
                # Check if line has pipe separator: "School Name | URL"
                if '|' in line:
                    parts = line.split('|', 1)
                    school_name = parts[0].strip()
                    link = parts[1].strip()
                
                # Check if line is a URL (starts with http)
                elif line.startswith('http'):
                    link = line
                    # Check if previous line was a school name
                    if i > 0:
                        prev_line = lines[i - 1].strip()
                        if prev_line and not prev_line.startswith('#') and not prev_line.startswith('http'):
                            school_name = prev_line
                
                # If line is not a URL, it might be a school name for next line
                else:
                    # This is a school name, URL should be on next line
                    i += 1
                    continue
                
                # Extract GUID from URL
                if link:
                    guid_match = re.search(r'guid=([^&\s]+)', link)
                    if guid_match:
                        guid = guid_match.group(1)
                        # URL decode once
                        import urllib.parse
                        guid = urllib.parse.unquote(guid)
                        
                        # Use provided name or generate placeholder
                        if not school_name:
                            school_name = f'School_{len(schools) + 1}'
                        
                        schools[school_name] = guid
                
                i += 1
            
            print(f'✅ Loaded {len(schools)} school(s) from {filename}\n')
            return schools
            
        except FileNotFoundError:
            print(f'❌ {filename} not found!')
            print(f'Create a {filename} file with status checker links.')
            print('\nFormat options:')
            print('  1. Just paste links (one per line)')
            print('  2. School name on one line, link on next')
            print('  3. School name | link (on same line)')
            print('\nExample:')
            print('Harvard Law School')
            print('https://aso.lsac-unite.org/?guid=abc123')
            print()
            print('Yale Law School | https://aso.lsac-unite.org/?guid=def456')
            return {}
    
    async def login(self, username, password, school_guid):
        """Login and capture token"""
        print('🔐 Logging in to LSAC...')
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            
            # Capture token from network requests
            async def handle_request(request):
                auth = request.headers.get('authorization', '')
                if auth.startswith('bearer '):
                    self.token = auth.replace('bearer ', '')
            
            page.on('request', handle_request)
            
            # Navigate to portal with GUID
            await page.goto(f'https://aso.lsac-unite.org/?guid={school_guid}')
            self.guid = school_guid
            
            # Wait for Azure B2C login page
            await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(2000)
            
            # Fill credentials
            await page.fill('input#logonIdentifier', username)
            await page.fill('input#password', password)
            
            # Submit
            await page.click('button#next')
            
            # Wait for redirect
            await page.wait_for_load_state('networkidle', timeout=60000)
            await page.wait_for_timeout(5000)
            
            await browser.close()
            
            if not self.token:
                raise Exception('Failed to capture authentication token')
            
            print('✅ Successfully logged in!\n')
    
    def get_status(self, school_guid):
        """Get application status for a school"""
        url = f'{self.api_base_url}/Schools/000/ApplicationStatus/0'
        
        response = requests.get(url, 
            params={
                'guid': school_guid,
                'subscription-key': self.subscription_key
            },
            headers={
                'Authorization': f'bearer {self.token}',
                'Ocp-Apim-Subscription-Key': self.subscription_key
            }
        )
        
        response.raise_for_status()
        return response.json()
    
    def get_school_name_from_response(self, data):
        """Extract school name from API response"""
        school_id = data.get('schoolId')
        
        # TODO: Find where school name is in the API response
        # For now, just show the school ID
        return f'School ID {school_id}'
    
    def display_status(self, data, school_name=None):
        """Display application status with all details"""
        # Use provided school name or fall back to School ID
        if not school_name:
            school_id = data.get('schoolId')
            school_name = f'School ID {school_id}'
        
        print('\n' + '='*70)
        print(f'📍 {school_name}')
        print('='*70)
        
        profile = data.get('profile', {})
        
        # Summary info
        print(f"\n📋 Applicant: {profile.get('firstName')} {profile.get('lastName')}")
        print(f"📧 Email: {profile.get('emailAddress')}")
        print(f"🆔 LSAC Account: {profile.get('lsacAcctNo')}")
        
        # Transcript status
        transcript = profile.get('transcript', {})
        if transcript.get('finalTranscript'):
            print(f"📄 Final Transcript: ✅ Received")
        
        # Application status for each program
        for app in data.get('applicationStatus', []):
            print('\n' + '-'*70)
            print(f"\n🎓 Program: {app.get('applicationTitle')}")
            
            # Current status - handle missing status gracefully
            status_list = app.get('status', {}).get('applicationStatus', [])
            if status_list and len(status_list) > 0:
                status_text = status_list[0].get('statusDisplayDescription', 'Unknown')
            else:
                status_text = 'Status information not available'
            print(f"📊 Status: {status_text}")
            
            # Status message
            message = app.get('message', {})
            if message and message.get('message'):
                # Strip HTML and clean up
                clean_msg = re.sub('<[^>]*>', '', message['message'])
                clean_msg = clean_msg.replace('&nbsp;', ' ').strip()
                if clean_msg:
                    print(f"\n💬 Message:")
                    print(f"   {clean_msg}")
            
            # Checklist
            checklist = app.get('checklist', [])
            if checklist:
                print(f"\n✓ Checklist:")
                for item in checklist:
                    icon = '✅' if item.get('isCompleted') else '⬜'
                    print(f"  {icon} {item.get('item')}")
            
            # Letters of recommendation
            lors = app.get('lor', [])
            if lors:
                print(f"\n📝 Letters of Recommendation: {len(lors)} submitted")
                for lor in lors:
                    name = f"{lor.get('prefix', '')} {lor.get('firstName', '')} {lor.get('lastName', '')}".strip()
                    date = lor.get('recommendationDate', '').split('T')[0]
                    signed = '✓' if lor.get('signatureFlag') else '✗'
                    print(f"  • {name} - {date} (Signed: {signed})")
            
            # Fee status
            fees = app.get('fee', [])
            if fees and fees[0]:
                fee = fees[0]
                fee_status = fee.get('displayDescription', 'Unknown')
                waived = fee.get('waivedFlag', False)
                print(f"\n💰 Application Fee: {fee_status}")
                if waived:
                    print(f"   (Waived)")
            
            # Scholarship info
            scholarships = app.get('scholarship', [])
            if scholarships and scholarships[0] and scholarships[0].get('scholarshipTypeName'):
                scholarship = scholarships[0]
                print(f"\n🎓 Scholarship: {scholarship.get('scholarshipTypeName')}")
                amount = scholarship.get('amount', 0)
                if amount > 0:
                    print(f"   Amount: ${amount:,.2f}")
        
        print('\n' + '='*70 + '\n')
    
    def save_token(self):
        """Save token to file"""
        with open('token.json', 'w') as f:
            json.dump({'token': self.token, 'guid': self.guid}, f)
    
    def load_token(self):
        """Load token from file"""
        try:
            with open('token.json', 'r') as f:
                data = json.load(f)
            self.token = data['token']
            self.guid = data['guid']
            print('✅ Loaded saved authentication token\n')
            return True
        except:
            return False
    
    def save_status_history(self, school_name, data):
        """Save current status to history file"""
        try:
            with open('status_history.json', 'r') as f:
                history = json.load(f)
        except:
            history = {}
        
        # Extract key status info
        status_info = {
            'timestamp': datetime.now().isoformat(),
            'school_id': data.get('schoolId'),
            'applications': []
        }
        
        for app in data.get('applicationStatus', []):
            status_list = app.get('status', {}).get('applicationStatus', [])
            current_status = status_list[0].get('statusDisplayDescription', 'Unknown') if status_list else 'Unknown'
            
            status_info['applications'].append({
                'program': app.get('applicationTitle'),
                'status': current_status,
                'checklist_complete': sum(1 for item in app.get('checklist', []) if item.get('isCompleted')),
                'checklist_total': len(app.get('checklist', []))
            })
        
        history[school_name] = status_info
        
        with open('status_history.json', 'w') as f:
            json.dump(history, f, indent=2)
    
    def check_for_changes(self, school_name, data):
        """Check if status changed since last run"""
        try:
            with open('status_history.json', 'r') as f:
                history = json.load(f)
        except:
            return []  # No history yet
        
        if school_name not in history:
            return []  # First time checking this school
        
        changes = []
        old_status = history[school_name]
        
        # Compare each application
        for i, app in enumerate(data.get('applicationStatus', [])):
            status_list = app.get('status', {}).get('applicationStatus', [])
            current_status = status_list[0].get('statusDisplayDescription', 'Unknown') if status_list else 'Unknown'
            
            if i < len(old_status['applications']):
                old_app = old_status['applications'][i]
                
                # Check if status changed
                if old_app['status'] != current_status:
                    changes.append({
                        'type': 'status',
                        'program': app.get('applicationTitle'),
                        'old': old_app['status'],
                        'new': current_status
                    })
                
                # Check if checklist items completed
                old_complete = old_app['checklist_complete']
                new_complete = sum(1 for item in app.get('checklist', []) if item.get('isCompleted'))
                
                if new_complete > old_complete:
                    changes.append({
                        'type': 'checklist',
                        'program': app.get('applicationTitle'),
                        'items_completed': new_complete - old_complete
                    })
        
        return changes


async def main():
    checker = LSACChecker()
    
    # Load credentials from .env file
    username = os.getenv('LSAC_USERNAME')
    password = os.getenv('LSAC_PASSWORD')
    
    if not username or not password:
        print('❌ Missing credentials!')
        print('Create a .env file with:')
        print('LSAC_USERNAME=your_username')
        print('LSAC_PASSWORD=your_password')
        return
    
    # Load schools from file
    schools = checker.load_schools_from_file('schools.txt')
    
    if not schools:
        return
    
    print(f'📚 Checking status for {len(schools)} school(s)...\n')
    
    # Login once (token works for all schools)
    if not checker.load_token():
        first_guid = list(schools.values())[0]
        await checker.login(username, password, first_guid)
        checker.save_token()
    
    # Check status for each school
    for school_name, school_guid in schools.items():
        try:
            print(f'Fetching status for {school_name}...')
            status = checker.get_status(school_guid)
            
            # Check for changes
            changes = checker.check_for_changes(school_name, status)
            
            if changes:
                print('\n' + '🚨 '*10)
                print(f'🎉 CHANGES DETECTED FOR {school_name.upper()}!')
                print('🚨 '*10)
                
                for change in changes:
                    if change['type'] == 'status':
                        print(f"\n📊 Status Update - {change['program']}")
                        print(f"   Old: {change['old']}")
                        print(f"   New: {change['new']}")
                    elif change['type'] == 'checklist':
                        print(f"\n✅ Checklist Progress - {change['program']}")
                        print(f"   {change['items_completed']} new item(s) completed!")
                
                print('\n' + '🚨 '*10 + '\n')
            
            # Display full status
            checker.display_status(status, school_name)
            
            # Save current status for next comparison
            checker.save_status_history(school_name, status)
            
        except requests.exceptions.HTTPError as e:
            if '400' in str(e):
                print(f'❌ Invalid GUID for {school_name} - check your schools.txt\n')
            else:
                print(f'❌ HTTP error for {school_name}: {e}\n')
        except Exception as e:
            print(f'❌ Error checking {school_name}: {e}\n')
    
    print('✅ Done!')


if __name__ == '__main__':
    asyncio.run(main())