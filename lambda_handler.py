"""
AWS Lambda handler for LSAC Status Checker
Runs the checker and sends results to SNS

Environment Variables Required:
- LSAC_USERNAME: Your LSAC username
- LSAC_PASSWORD: Your LSAC password
- SNS_TOPIC_ARN: ARN of the SNS topic to publish notifications
- TIMEZONE: Optional, defaults to 'America/New_York'

Lambda Configuration:
- Runtime: Python 3.11+
- Architecture: x86_64 (for Playwright compatibility)
- Memory: 2048 MB (minimum for Chromium)
- Timeout: 300 seconds (5 minutes)
- Layer: Playwright Lambda layer (see README for setup)
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import boto3
from smart_open import open as smart_open

from lsac_checker import EMAIL_TRACKING_FILE
from lsac_checker import main as lsac_main

# Force headless mode for Lambda environment
os.environ['RUN_HEADLESS'] = 'true'

sns_client = boto3.client('sns')

# Email tracking constants
NO_CHANGE_EMAIL_HOUR = 9  # Only send "no changes" emails at 9am Eastern


def load_email_tracking():
    """Load email tracking data (last email timestamp and whether it had changes)"""
    try:
        with smart_open(EMAIL_TRACKING_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_email_tracking(had_changes):
    """Save email tracking data after sending an email"""
    tracking_data = {
        'last_email_sent': datetime.now().isoformat(),
        'last_email_had_changes': had_changes,
    }
    try:
        with smart_open(EMAIL_TRACKING_FILE, 'w') as f:
            json.dump(tracking_data, f, indent=2)
    except Exception as e:
        print(f'⚠️  Warning: Could not save email tracking to {EMAIL_TRACKING_FILE}: {e}')


def should_send_email(has_changes):
    """
    Determine if an email should be sent based on:
    - Always send if there are changes
    - If no changes, only send during the 9am Eastern hour AND no email sent since 9am

    Returns tuple: (should_send: bool, reason: str)
    """
    if has_changes:
        return True, 'changes_detected'

    # Only send "no changes" emails at 9am Eastern
    tz = ZoneInfo(os.environ.get('TIMEZONE', 'America/New_York'))
    current_hour = datetime.now(tz).hour

    if current_hour != NO_CHANGE_EMAIL_HOUR:
        return False, f'no_changes_not_9am_hour_(current_hour={current_hour})'

    # It's 9am - check if we already sent an email today
    tracking = load_email_tracking()
    last_email_sent = tracking.get('last_email_sent')

    if not last_email_sent:
        return True, 'no_changes_9am_no_previous_email'

    try:
        last_email_time = datetime.fromisoformat(last_email_sent)
        # Make timezone-aware if not already
        if last_email_time.tzinfo is None:
            last_email_time = last_email_time.replace(tzinfo=tz)

        # Calculate when yesterday's 9am was
        now = datetime.now(tz)
        today_9am = now.replace(hour=NO_CHANGE_EMAIL_HOUR, minute=0, second=0, microsecond=0)
        yesterday_9am = today_9am - timedelta(days=1)

        # Only send if no email has been sent since yesterday's 9am
        if last_email_time < yesterday_9am:
            return True, 'no_changes_9am_daily_update'
        else:
            return False, 'no_changes_9am_but_email_sent_since_yesterday_9am'
    except Exception as e:
        return True, f'no_changes_9am_timestamp_parse_error: {e}'


def lambda_handler(event, context):
    """
    Lambda handler that runs the LSAC checker and publishes results to SNS

    Returns:
        dict: Lambda response with status code and body
    """

    sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')

    if not sns_topic_arn:
        return {'statusCode': 500, 'body': json.dumps({'error': 'SNS_TOPIC_ARN environment variable not set'})}

    # Capture stdout to collect the checker output
    old_stdout = sys.stdout
    sys.stdout = captured_output = StringIO()

    try:
        # Run the existing main function
        asyncio.run(lsac_main())

        # Get the captured output
        output = captured_output.getvalue()

        # Restore stdout
        sys.stdout = old_stdout

        # Parse output for better subject lines
        has_changes = '🚨' in output
        schools_checked = output.count('Fetching status for')
        changes_detected = output.count('CHANGES DETECTED')

        # Determine if we should send an email
        send_email, email_reason = should_send_email(has_changes)

        # Create dynamic subject line
        if has_changes:
            if changes_detected == 1:
                # Try to extract school name
                lines = output.split('\n')
                school_name = None
                for line in lines:
                    if 'CHANGES DETECTED FOR' in line:
                        school_name = line.split('FOR')[1].strip('!').strip()
                        break

                if school_name:
                    subject = f'🚨 LSAC Update: {school_name}'
                else:
                    subject = '🚨 LSAC Status Update Detected'
            else:
                subject = f'🚨 LSAC Updates: {changes_detected} Schools Changed'
        else:
            if schools_checked > 0:
                subject = f'✅ LSAC Check Complete ({schools_checked} Schools - No Changes)'
            else:
                subject = 'LSAC Status Check Complete'

        message = f"""LSAC Status Check Results
Time: {datetime.now().isoformat()}
Schools Checked: {schools_checked}
Changes Detected: {changes_detected}

{output}

---
Automated check from AWS Lambda
"""

        # Publish to SNS only if we should send an email
        if send_email:
            response = sns_client.publish(TopicArn=sns_topic_arn, Subject=subject, Message=message)
            save_email_tracking(has_changes)
            sns_message_id = response['MessageId']
        else:
            sns_message_id = None

        return {
            'statusCode': 200,
            'body': json.dumps(
                {
                    'message': 'Check completed successfully',
                    'changes_detected': has_changes,
                    'email_sent': send_email,
                    'email_reason': email_reason,
                    'sns_message_id': sns_message_id,
                }
            ),
        }

    except Exception as e:
        # Restore stdout
        sys.stdout = old_stdout
        output = captured_output.getvalue()

        error_message = f"""LSAC Status Check Error
Time: {datetime.now().isoformat()}

Error: {str(e)}

Partial output:
{output}

---
Automated check from AWS Lambda
"""

        # Still try to send error notification to SNS
        try:
            sns_client.publish(TopicArn=sns_topic_arn, Subject='❌ LSAC Status Check Error', Message=error_message)
        except Exception:
            pass  # If SNS fails, just log the error

        return {'statusCode': 500, 'body': json.dumps({'error': str(e), 'output': output})}
