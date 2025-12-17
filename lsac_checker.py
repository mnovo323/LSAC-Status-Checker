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

import asyncio
import base64
import json
import os
import re
from datetime import datetime

import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from smart_open import open as smart_open

# Try to import boto3 for AWS Secrets Manager support
try:
    import boto3

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

# Load environment variables from .env file
load_dotenv()

# Configuration constants
RUN_HEADLESS = os.getenv('RUN_HEADLESS', 'true').lower() in ('true', '1', 'yes')
TIMEZONE = os.getenv('TIMEZONE', 'America/New_York')
LSAC_CREDENTIALS_SECRET = os.getenv('LSAC_CREDENTIALS_SECRET')
S3_BUCKET = os.getenv('S3_BUCKET')  # If set, use S3; otherwise use local files

# File locations - automatically use S3 if S3_BUCKET is configured
if S3_BUCKET:
    SCHOOLS_FILE = os.getenv('SCHOOLS_FILE', f's3://{S3_BUCKET}/schools.txt')
    STATUS_HISTORY_FILE = f's3://{S3_BUCKET}/status_history.json'
    TOKEN_FILE = f's3://{S3_BUCKET}/token.json'
    EMAIL_TRACKING_FILE = f's3://{S3_BUCKET}/email_tracking.json'
else:
    SCHOOLS_FILE = os.getenv('SCHOOLS_FILE', 'schools.txt')
    STATUS_HISTORY_FILE = 'status_history.json'
    TOKEN_FILE = 'token.json'
    EMAIL_TRACKING_FILE = 'email_tracking.json'


# Helper functions
def load_credentials():
    """
    Load LSAC credentials from Secrets Manager (if configured) or environment variables.
    Priority: Secrets Manager > Environment Variables
    """
    if LSAC_CREDENTIALS_SECRET and BOTO3_AVAILABLE:
        try:
            client = boto3.client('secretsmanager')
            response = client.get_secret_value(SecretId=LSAC_CREDENTIALS_SECRET)
            secret = json.loads(response['SecretString'])
            return secret.get('username'), secret.get('password')
        except Exception as e:
            print(f'⚠️  Could not load credentials from Secrets Manager: {e}')
            print('   Falling back to environment variables...')

    # Fall back to environment variables
    return os.getenv('LSAC_USERNAME'), os.getenv('LSAC_PASSWORD')


class LSACChecker:
    def __init__(self):
        self.subscription_key = 'b2acf0d4d39d47bb8405b947e0282a04'
        self.api_base_url = 'https://aces-prod-apimgmt.azure-api.net/aso/api/v1'
        self.token = None
        self.guid = None

    def load_schools_from_file(self, filename=None):
        """
        Load school status checker links from file and extract GUIDs
        Supports local files and S3 URIs (s3://bucket/key)

        Format options in schools.txt:

        Option 1 - Just the link:
        https://aso.lsac-unite.org/?guid=xjQd2C0H4WM%3d

        Option 2 - School name, then link:
        Cooley Law School
        https://aso.lsac-unite.org/?guid=abc123

        Option 3 - School name with pipe separator:
        Yale Law School | https://aso.lsac-unite.org/?guid=def456
        """
        if filename is None:
            filename = SCHOOLS_FILE

        schools = {}

        try:
            # smart_open handles both local files and S3 URIs
            with smart_open(filename, 'r') as f:
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
            print('Cooley Law School')
            print('https://aso.lsac-unite.org/?guid=abc123')
            print()
            print('Yale Law School | https://aso.lsac-unite.org/?guid=def456')
            return {}
        except Exception as e:
            print(f'❌ Error loading schools file from {filename}: {e}')
            print('If using S3, ensure the file exists and Lambda has read permissions.')
            return {}

    async def login(self, username, password, school_guid):
        """Login and capture token"""
        print('🔐 Logging in to LSAC...')

        if not RUN_HEADLESS:
            print('🖥️  Running in headed mode (browser window will be visible)')

        async with async_playwright() as p:
            # Configure browser launch based on headless mode
            if RUN_HEADLESS:
                # Headless mode requires stealth settings to avoid bot detection
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-gpu',
                        '--single-process',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-software-rasterizer',
                    ],
                )
                # Create context with realistic browser settings
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    locale='en-US',
                    timezone_id=TIMEZONE,
                )
                page = await context.new_page()

                # Hide webdriver property for stealth
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
            else:
                # Headed mode: simple configuration
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

        response = requests.get(
            url,
            params={'guid': school_guid, 'subscription-key': self.subscription_key},
            headers={'Authorization': f'bearer {self.token}', 'Ocp-Apim-Subscription-Key': self.subscription_key},
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

        print('\n' + '=' * 70)
        print(f'📍 {school_name}')
        print('=' * 70)

        profile = data.get('profile', {})

        # Summary info
        print(f"\n📋 Applicant: {profile.get('firstName')} {profile.get('lastName')}")
        print(f"📧 Email: {profile.get('emailAddress')}")
        print(f"🆔 LSAC Account: {profile.get('lsacAcctNo')}")

        # Transcript status
        transcript = profile.get('transcript', {})
        if transcript.get('finalTranscript'):
            print('📄 Final Transcript: ✅ Received')

        # Application status for each program
        for app in data.get('applicationStatus', []):
            print('\n' + '-' * 70)
            print(f"\n🎓 Program: {app.get('applicationTitle')}")

            # Current status - handle missing status gracefully
            status_list = app.get('status', {}).get('applicationStatus', [])
            if status_list and len(status_list) > 0:
                status_text = status_list[0].get('statusDisplayDescription', 'Unknown')
            else:
                status_text = 'Status information not available'
            print(f'📊 Status: {status_text}')

            # Status message
            message = app.get('message', {})
            if message and message.get('message'):
                # Strip HTML and clean up
                clean_msg = re.sub('<[^>]*>', '', message['message'])
                clean_msg = clean_msg.replace('&nbsp;', ' ').strip()
                if clean_msg:
                    print('\n💬 Message:')
                    print(f'   {clean_msg}')

            # Checklist
            checklist = app.get('checklist', [])
            if checklist:
                print('\n✓ Checklist:')
                for item in checklist:
                    icon = '✅' if item.get('isCompleted') else '⬜'
                    print(f"  {icon} {item.get('item')}")

            # Letters of recommendation
            lors = app.get('lor', [])
            if lors:
                print(f'\n📝 Letters of Recommendation: {len(lors)} submitted')
                for lor in lors:
                    name = f"{lor.get('prefix', '')} {lor.get('firstName', '')} {lor.get('lastName', '')}".strip()
                    date = lor.get('recommendationDate', '').split('T')[0]
                    signed = '✓' if lor.get('signatureFlag') else '✗'
                    print(f'  • {name} - {date} (Signed: {signed})')

            # Fee status
            fees = app.get('fee', [])
            if fees and fees[0]:
                fee = fees[0]
                fee_status = fee.get('displayDescription', 'Unknown')
                waived = fee.get('waivedFlag', False)
                print(f'\n💰 Application Fee: {fee_status}')
                if waived:
                    print('   (Waived)')

            # Scholarship info
            scholarships = app.get('scholarship', [])
            if scholarships and scholarships[0] and scholarships[0].get('scholarshipTypeName'):
                scholarship = scholarships[0]
                print(f"\n🎓 Scholarship: {scholarship.get('scholarshipTypeName')}")
                amount = scholarship.get('amount', 0)
                if amount > 0:
                    print(f'   Amount: ${amount:,.2f}')

        print('\n' + '=' * 70 + '\n')

    def save_token(self):
        """Save token to Secrets Manager (AWS) or file (local) with expiration info"""
        # Decode JWT to get expiration
        try:
            parts = self.token.split('.')
            payload = parts[1]
            payload += '=' * (4 - len(payload) % 4)
            decoded = base64.b64decode(payload)
            token_data = json.loads(decoded)
            expires_at = token_data.get('exp')
        except Exception:
            # If we can't decode, assume 24 hours from now
            expires_at = int(datetime.now().timestamp()) + (24 * 60 * 60)

        token_payload = {'token': self.token, 'guid': self.guid, 'expires_at': expires_at}

        # If running in AWS (Secrets Manager configured), save to Secrets Manager
        if LSAC_CREDENTIALS_SECRET and BOTO3_AVAILABLE:
            try:
                client = boto3.client('secretsmanager')
                # Get existing secret
                response = client.get_secret_value(SecretId=LSAC_CREDENTIALS_SECRET)
                secret_data = json.loads(response['SecretString'])
                # Add token data to existing credentials
                secret_data['token_data'] = token_payload
                # Update secret
                client.update_secret(SecretId=LSAC_CREDENTIALS_SECRET, SecretString=json.dumps(secret_data))
                print('✅ Saved token to AWS Secrets Manager')
                return
            except Exception as e:
                print(f'⚠️  Warning: Could not save token to Secrets Manager: {e}')
                print('   Falling back to file storage...')

        # Local file storage (fallback or when not running in AWS)
        try:
            with smart_open(TOKEN_FILE, 'w') as f:
                json.dump(token_payload, f)
        except Exception as e:
            print(f'⚠️  Warning: Could not save token to {TOKEN_FILE}: {e}')

    def load_token(self):
        """Load token from Secrets Manager (AWS) or file (local) and check if expired"""
        data = None

        # If running in AWS (Secrets Manager configured), try loading from Secrets Manager
        if LSAC_CREDENTIALS_SECRET and BOTO3_AVAILABLE:
            try:
                client = boto3.client('secretsmanager')
                response = client.get_secret_value(SecretId=LSAC_CREDENTIALS_SECRET)
                secret_data = json.loads(response['SecretString'])
                data = secret_data.get('token_data')
                if not data:
                    print('⚠️  No token found in Secrets Manager\n')
                    return False
            except Exception as e:
                print(f'⚠️  Error loading token from Secrets Manager: {e}\n')
                return False
        else:
            # Local file storage
            try:
                with smart_open(TOKEN_FILE, 'r') as f:
                    data = json.load(f)
            except FileNotFoundError:
                return False
            except Exception as e:
                print(f'⚠️  Error loading token: {e}\n')
                return False

        if not data:
            return False

        # Check if token is expired
        expires_at = data.get('expires_at', 0)
        current_time = int(datetime.now().timestamp())

        if current_time >= expires_at:
            print('⚠️  Saved token has expired, need to re-authenticate\n')
            return False

        # Calculate time until expiration
        time_left = expires_at - current_time
        hours_left = time_left // 3600
        minutes_left = (time_left % 3600) // 60

        self.token = data['token']
        self.guid = data['guid']
        print(f'✅ Loaded saved authentication token (expires in {hours_left}h {minutes_left}m)\n')
        return True

    def save_status_history(self, school_name, data):
        """Save current status to history file"""
        try:
            with smart_open(STATUS_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception:
            history = {}

        # Extract key status info
        status_info = {'timestamp': datetime.now().isoformat(), 'school_id': data.get('schoolId'), 'applications': []}

        for app in data.get('applicationStatus', []):
            status_list = app.get('status', {}).get('applicationStatus', [])
            current_status = status_list[0].get('statusDisplayDescription', 'Unknown') if status_list else 'Unknown'

            status_info['applications'].append(
                {
                    'program': app.get('applicationTitle'),
                    'status': current_status,
                    'checklist_complete': sum(1 for item in app.get('checklist', []) if item.get('isCompleted')),
                    'checklist_total': len(app.get('checklist', [])),
                }
            )

        history[school_name] = status_info

        try:
            with smart_open(STATUS_HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            print(f'⚠️  Warning: Could not save status history to {STATUS_HISTORY_FILE}: {e}')

    def check_for_changes(self, school_name, data):
        """Check if status changed since last run"""
        try:
            with smart_open(STATUS_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception:
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
                    changes.append(
                        {
                            'type': 'status',
                            'program': app.get('applicationTitle'),
                            'old': old_app['status'],
                            'new': current_status,
                        }
                    )

                # Check if checklist items completed
                old_complete = old_app['checklist_complete']
                new_complete = sum(1 for item in app.get('checklist', []) if item.get('isCompleted'))

                if new_complete > old_complete:
                    changes.append(
                        {
                            'type': 'checklist',
                            'program': app.get('applicationTitle'),
                            'items_completed': new_complete - old_complete,
                        }
                    )

        return changes


async def main():
    checker = LSACChecker()

    # Load credentials (from Secrets Manager if available, otherwise from .env)
    username, password = load_credentials()

    if not username or not password:
        print('❌ Missing credentials!')
        print('Create a .env file with:')
        print('LSAC_USERNAME=your_username')
        print('LSAC_PASSWORD=your_password')
        return

    # Load schools from file (uses SCHOOLS_FILE env var, defaults to 'schools.txt')
    schools = checker.load_schools_from_file()

    if not schools:
        return

    print(f'📚 Checking status for {len(schools)} school(s)...\n')

    # Login once (token works for all schools)
    if not checker.load_token():
        first_guid = list(schools.values())[0]
        await checker.login(username, password, first_guid)
        checker.save_token()

    changes_log = []

    # Check status for each school
    for school_name, school_guid in schools.items():
        try:
            print(f'Fetching status for {school_name}...')
            status = checker.get_status(school_guid)

            # Check for changes
            changes = checker.check_for_changes(school_name, status)

            if changes:
                print('\n' + '🚨 ' * 10)
                print(f'🎉 CHANGES DETECTED FOR {school_name.upper()}!')
                print('🚨 ' * 10)

                changes_log.append({'school': school_name, 'changes': changes})

                for change in changes:
                    if change['type'] == 'status':
                        print(f"\n📊 Status Update - {change['program']}")
                        print(f"   Old: {change['old']}")
                        print(f"   New: {change['new']}")
                    elif change['type'] == 'checklist':
                        print(f"\n✅ Checklist Progress - {change['program']}")
                        print(f"   {change['items_completed']} new item(s) completed!")

                print('\n' + '🚨 ' * 10 + '\n')

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

    if changes_log:
        print('Summary of Changes Detected:')
        for entry in changes_log:
            print(f"\n🏫 {entry['school']}:")
            for change in entry['changes']:
                if change['type'] == 'status':
                    print(f"  📊 Status Change - {change['program']}: {change['old']} -> {change['new']}")
                elif change['type'] == 'checklist':
                    print(
                        f"  ✅ Checklist Progress - {change['program']}: {change['items_completed']} new item(s) completed"
                    )
    else:
        print('No changes detected across all schools.')

    print('✅ Done!')


if __name__ == '__main__':
    asyncio.run(main())
