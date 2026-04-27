import requests

def personalize_template(template, lead):
    for key, value in lead.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template

def simulate_outreach(leads_df, template):
    print(f"\n🚀 Sending sequence to {len(leads_df)} high-intent leads...")
    for _, lead in leads_df.iterrows():
        email = personalize_template(template, lead)
        print(f"→ To: {lead['Name']} ({lead['Email']})")
        print(f"   Subject: Quick question about your {lead['Signal']}")
        print(f"   Preview: {email[:120]}...\n")

def send_via_formsubmit(target_email, lead, template):
    """Send an email via FormSubmit and return (ok, message)."""
    url = f"https://formsubmit.co/ajax/{target_email}"
    email_body = personalize_template(template, lead)
    
    # Matching the 'name' attributes mentioned in instructions
    payload = {
        "name": lead['Name'],
        "email": lead['Email'],
        "company": lead['Company'],
        "message": email_body,
        "_subject": f"IntentFlow Outreach: {lead['Name']} ({lead['Company']})",
        "_captcha": "false" # Disable captcha for AJAX
    }
    
    try:
        # FormSubmit returns JSON with success=true/false even on HTTP 200.
        response = requests.post(
            url,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                # FormSubmit checks for browser-style origins for AJAX submissions.
                "Origin": "http://localhost:8501",
                "Referer": "http://localhost:8501/"
            },
            timeout=20
        )
        if response.status_code != 200:
            return False, f"Dispatch failed (HTTP {response.status_code})."

        try:
            body = response.json()
        except ValueError:
            return False, "Dispatch failed: non-JSON response from FormSubmit."

        success = str(body.get("success", "")).lower() == "true"
        message = body.get("message", "")
        if success:
            return True, "Email dispatched successfully."
        return False, message or "Dispatch was rejected by FormSubmit."
    except Exception as e:
        return False, f"Error sending to FormSubmit: {e}"
