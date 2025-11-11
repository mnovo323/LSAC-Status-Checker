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
from datetime import datetime
from io import StringIO

import boto3

# Force headless mode for Lambda environment
os.environ['RUN_HEADLESS'] = 'true'

# Import the existing checker
from lsac_checker import main as lsac_main

sns_client = boto3.client('sns')


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

        # Publish to SNS
        response = sns_client.publish(TopicArn=sns_topic_arn, Subject=subject, Message=message)

        return {
            'statusCode': 200,
            'body': json.dumps(
                {
                    'message': 'Check completed successfully',
                    'changes_detected': has_changes,
                    'sns_message_id': response['MessageId'],
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
