# LSAC Status Checker

Automatically check your law school application statuses without logging into multiple portals. Get notified when your status changes!

## Features

- ✅ **Multi-School Support** - Check all your applications at once
- 🚨 **Change Detection** - Get alerted when statuses update or checklist items complete
- 💾 **Smart Caching** - Authentication token saved for 24 hours (no repeated logins)
- 📊 **Comprehensive Info** - View status, checklists, letters of recommendation, fees, and scholarships
- 🔒 **Secure** - Credentials stored locally in `.env` file

## Prerequisites

- Python 3.8+
- LSAC account with applications submitted

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/lsac-status-checker.git
   cd lsac-status-checker
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Create `.env` file**
   
   **Linux/Mac:**
   ```bash
   echo "LSAC_USERNAME=your_username" > .env
   echo "LSAC_PASSWORD=your_password" >> .env
   ```
   
   **Windows (PowerShell):**
   ```powershell
   @"
   LSAC_USERNAME=your_username
   LSAC_PASSWORD=your_password
   "@ | Out-File -FilePath .env -Encoding utf8
   ```
   
   **Windows (Command Prompt):**
   ```cmd
   echo LSAC_USERNAME=your_username > .env
   echo LSAC_PASSWORD=your_password >> .env
   ```
   
   **Or just create the file manually:**
   - Create a new file named `.env` (note the leading dot)
   - Add these two lines:
     ```
     LSAC_USERNAME=your_username
     LSAC_PASSWORD=your_password
     ```

4. **Create `schools.txt` file**
   
   Add your school status checker links. Get these from:
   - Emails from law schools with "Check Application Status" links
   - Law school admissions portals
   - LSAC status checker emails
   
   **Format options:**
   
   ```txt
   # Option 1: Just paste the link
   https://aso.lsac-unite.org/?guid=xjQd2C0H4WM%3d
   
   # Option 2: School name on line above link
   Cooley Law School
   https://aso.lsac-unite.org/?guid=abc123
   
   # Option 3: School name | link (same line)
   Yale Law School | https://aso.lsac-unite.org/?guid=def456
   
   # Mix and match any format!
   ```

## Usage

Run the checker:

```bash
python lsac_checker.py
```

**First run:**
- Browser window will open
- Logs you in automatically
- Shows all application statuses
- Saves status to `status_history.json`

**Subsequent runs:**
- Uses saved authentication token (no browser needed for 24 hours)
- Compares with previous status
- Shows 🚨 alerts for any changes

## Example Output

```
✅ Loaded 5 school(s) from schools.txt

📚 Checking status for 5 school(s)...

✅ Loaded saved authentication token

Fetching status for Cooley Law School...

🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 
🎉 CHANGES DETECTED FOR COOLEY LAW SCHOOL!
🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 

📊 Status Update - Fall 2026 Full Time JD
   Old: Application Under Review
   New: Admitted

🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 🚨 

======================================================================
📍 Cooley Law School
======================================================================

📋 Applicant: John Doe
📧 Email: john@example.com
🆔 LSAC Account: L12345678
📄 Final Transcript: ✅ Received

----------------------------------------------------------------------

🎓 Program: Fall 2026 Full Time JD
📊 Status: Admitted

💬 Message:
   Congratulations! You have been admitted to Cooley Law School...

✓ Checklist:
  ✅ Personal Statement
  ✅ Letters of Recommendation
  ✅ Resume

📝 Letters of Recommendation: 3 submitted
  • Prof. Jane Smith - 2025-08-15 (Signed: ✓)
  • Dr. Bob Johnson - 2025-08-20 (Signed: ✓)
  • Dean Mary Williams - 2025-08-25 (Signed: ✓)

💰 Application Fee: Application Fee Paid
   (Waived)

======================================================================
```

## Automation

Set up a daily check using cron (Linux/Mac) or Task Scheduler (Windows):

### Linux/Mac (cron)

```bash
# Run daily at 9 AM
0 9 * * * cd /path/to/lsac-status-checker && /usr/bin/python3 lsac_checker.py >> lsac.log 2>&1
```

### Windows (Task Scheduler)

1. Open Task Scheduler
2. Create Basic Task
3. Trigger: Daily at 9:00 AM
4. Action: Start a program
   - Program: `python`
   - Arguments: `C:\path\to\lsac_checker.py`
   - Start in: `C:\path\to\lsac-status-checker`

## Files Created

- `token.json` - Cached authentication token (expires after 24 hours)
- `status_history.json` - Previous status for change detection
- `lsac.log` - Optional log file if you redirect output

## Troubleshooting

### "Failed to capture token"
- Token capture failed during login. Try running again.
- Check if your credentials in `.env` are correct
- Make sure Chromium is installed: `playwright install chromium`

### "Invalid GUID"
- One of your status checker links is incorrect
- Make sure you copied the full URL including `?guid=...`
- Check for duplicate GUIDs in `schools.txt`

### "400 Bad Request"
- The GUID might be URL-encoded incorrectly
- Try copying the link directly from your email/portal again

### Browser doesn't close
- The script is still running - wait for it to complete
- If stuck, press Ctrl+C to cancel

## Privacy & Security

- ⚠️ **Never commit your `.env` file** - it contains your credentials
- All data stays local on your machine
- No data is sent anywhere except to LSAC's official servers
- Open source - review the code yourself!

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Limitations

- Only works for schools using LSAC's unified status portal (`aso.lsac-unite.org`)
- Requires valid LSAC credentials
- Token expires after 24 hours (automatic re-login on next run)

## License

MIT License - See LICENSE file for details

## Disclaimer

This tool is not affiliated with or endorsed by LSAC. Use responsibly and in accordance with LSAC's terms of service. Automated access may be against their ToS - use at your own risk.

## Support

Having issues? 

1. Check the [Troubleshooting](#troubleshooting) section
2. Open an issue on GitHub
3. Make sure you're using Python 3.8+

## Acknowledgments

Built by law school applicants, for law school applicants. Good luck with your applications! 🎓⚖️

---

**Star ⭐ this repo if it helped you!**