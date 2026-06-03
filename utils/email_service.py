from flask_mail import Message
from flask import current_app
from extensions import mail # adjust import if needed
from utils.email_config_service import DELIVERY_TEST, get_email_delivery_config

def send_email(subject, recipients, body):
    try:
        config = get_email_delivery_config()
        final_recipients = list(recipients or [])
        final_subject = subject
        final_body = body

        if config.delivery_mode == DELIVERY_TEST and config.test_address:
            original_recipients = ", ".join(final_recipients) if final_recipients else "No intended recipients"
            final_recipients = [config.test_address]
            final_subject = f"[TEST ROUTED] {subject}"
            final_body = (
                f"Original intended recipients: {original_recipients}\n\n"
                f"{body}"
            )

        msg = Message(
            subject=final_subject,
            sender=current_app.config.get('MAIL_USERNAME'),
            recipients=final_recipients,
            body=final_body
        )
        mail.send(msg)
        current_app.logger.info("Email sent", extra={"subject": final_subject, "recipients": final_recipients})
    except Exception as e:
        current_app.logger.exception("Email failed: %s", str(e))
