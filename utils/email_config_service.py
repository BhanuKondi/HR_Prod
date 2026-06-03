from models.db import db
from models.models import EmailDeliveryConfig


DELIVERY_INTENDED = "intended_recipients"
DELIVERY_TEST = "test_address"


def get_email_delivery_config() -> EmailDeliveryConfig:
    config = EmailDeliveryConfig.query.order_by(EmailDeliveryConfig.id.asc()).first()
    if config:
        return config

    config = EmailDeliveryConfig(delivery_mode=DELIVERY_INTENDED, test_address=None)
    db.session.add(config)
    db.session.commit()
    return config
