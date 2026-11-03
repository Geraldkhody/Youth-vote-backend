def normalize_phone(phone):
    """Turn a Ghanaian phone number into the stored format: 233XXXXXXXXX.

    Accepts three input formats:
      - 0XXXXXXXXX     (10 digits, starts with 0)
      - 233XXXXXXXXX   (12 digits, starts with 233)
      - +233XXXXXXXXX  (starts with +233)

    Returns the normalised number as a string, or None if the input doesn't
    match any of those formats.
    """
    if not phone:
        return None

    phone = phone.strip()

    if phone.startswith("+233"):
        phone = phone[1:]

    if phone.startswith("0") and len(phone) == 10 and phone.isdigit():
        return "233" + phone[1:]

    if phone.startswith("233") and len(phone) == 12 and phone.isdigit():
        return phone

    return None
