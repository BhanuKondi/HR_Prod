from __future__ import annotations

from models.db import db
from models.models import Company


DEFAULT_COMPANIES = [
    {
        "code": "ATIKES-SPL",
        "display_name": "ATIKES Secure Private Limited",
        "legal_name": "ATIKES Secure Private Limited",
        "gst_number": "37ABDCA3369B1ZW",
        "address": (
            "#4-36/1, Near Railway Station\n"
            "Gopalapatnam, Tondangi Mandalam\n"
            "East Godavari, AP, INDIA - 533408"
        ),
    },
    {
        "code": "ATIKES",
        "display_name": "ATIKES",
        "legal_name": "ATIKES",
        "gst_number": "37BORPA3261B2Z7",
        "address": (
            "#4-36/1, Near Railway Station\n"
            "Gopalapatnam, Tondangi Mandalam\n"
            "East Godavari, AP, INDIA - 533408"
        ),
    },
]


def seed_companies() -> None:
    existing = {company.code.lower(): company for company in Company.query.all()}
    changed = False

    for company_data in DEFAULT_COMPANIES:
        key = company_data["code"].lower()
        company = existing.get(key)
        if company:
            company.display_name = company_data["display_name"]
            company.legal_name = company_data["legal_name"]
            company.gst_number = company_data["gst_number"]
            company.address = company_data["address"]
            company.is_active = True
        else:
            db.session.add(Company(**company_data, is_active=True))
        changed = True

    if changed:
        db.session.commit()


def get_active_companies():
    return Company.query.filter_by(is_active=True).order_by(Company.display_name.asc()).all()

