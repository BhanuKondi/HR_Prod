import os
import smtplib
from email.mime.text import MIMEText


SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL = os.getenv("SMTP_EMAIL", "")
PASSWORD = os.getenv("SMTP_PASSWORD", "")
TO_EMAIL = os.getenv("SMTP_TO_EMAIL", "")


def main():
    if not EMAIL or not PASSWORD or not TO_EMAIL:
        raise SystemExit(
            "Set SMTP_EMAIL, SMTP_PASSWORD, and SMTP_TO_EMAIL before running this test."
        )

    msg = MIMEText("SMTP Test Successful")
    msg["Subject"] = "SMTP Test Email"
    msg["From"] = EMAIL
    msg["To"] = TO_EMAIL

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL, PASSWORD)
        server.sendmail(EMAIL, TO_EMAIL, msg.as_string())
    print("Email sent successfully")


if __name__ == "__main__":
    main()
