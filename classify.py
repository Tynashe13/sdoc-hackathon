"""Stage 1: what kind of email is this?  Cheap rules first, LLM only if unsure."""
import re

SPAM = re.compile(r"guaranteed|click here|gift card|bank details|urgent business proposal|unpaid|customs fee|"
                  r"limited time|\d+% off|bitcoin|verify (your )?account|you have won|"
                  r"claim your|selected in our", re.I)


def body_core(email):
    """Body without the signature block / quoted reply chain."""
    body = email["body"]
    body = re.split(r"\n\s*(?:Best Regards|Best,|Regards|Warm regards)|\n_{5,}|\nFrom:", body)[0]
    return re.sub(r"\s+", " ", body).strip()


def classify_by_rules(email):
    """-> category, or None when the rules are not confident (caller may ask the LLM)."""
    text = body_core(email).lower()
    subject = email["subject"].lower()
    if SPAM.search(text) or SPAM.search(subject):
        return "SPAM"
    if re.search(r"automated notification|no action required", text):
        return "GENERAL"
    # new SI request: the sender pastes shipment details for us to prepare an SI
    # (checked before BL: these mails end with "please revert with draft BL")
    if re.search(r"shipping instruction for", text) and ("pol:" in text or "shipper:" in text):
        return "SI_REQUEST"
    # document check: talks about the BL + a check/compare/send-draft action
    if re.search(r"draft bl|draft bill of lading|confirm the bl is in order", text):
        return "BL_COMPARISON"
    if re.search(r"invoice|\bgr\b|thc|pgi|billing|charges|detention|d&d", text):
        return "INVOICE_QUERY"
    if re.search(r"berthing report|update summary|outstanding|new year|reminder", text):
        return "GENERAL"
    return None
