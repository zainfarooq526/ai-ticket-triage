"""Sample tickets used by the dashboard demo button and the send_webhook script."""

SAMPLE_TICKETS: list[dict] = [
    {
        "ticket_id": 10421,
        "subject": "Checkout is down for all our customers",
        "description": "Since 9:40am every checkout on our store returns a 502. Nobody can pay. "
        "We're losing thousands per hour, please escalate ASAP.",
        "requester_name": "Priya Raman",
        "requester_email": "priya@example-shop.com",
        "priority": "normal",
        "tags": "enterprise",
    },
    {
        "ticket_id": 10422,
        "subject": "Charged twice for November",
        "description": "Hi, my card was charged twice for the Pro plan this month. Can I get a refund "
        "for the duplicate? Invoice #88213.",
        "requester_name": "Marcus Lee",
        "requester_email": "marcus@example.com",
        "tags": "",
    },
    {
        "ticket_id": 10423,
        "subject": "Dark mode would be great",
        "description": "Love the product! Would love a dark mode option for late-night work. Thanks!",
        "requester_name": "Ana Souza",
        "requester_email": "ana@example.com",
        "tags": "",
    },
    {
        "ticket_id": 10424,
        "subject": "Locked out after 2FA reset",
        "description": "I reset my phone and now I'm locked out of my account. I can't approve payroll "
        "and it's due today. This is unacceptable.",
        "requester_name": "Devon Clarke",
        "requester_email": "devon@example.org",
        "tags": "",
    },
    {
        "ticket_id": 10425,
        "subject": "CSV export has wrong dates",
        "description": "When I export reports to CSV the dates are shifted by one day. Exporting to PDF "
        "works fine so I'm using that for now.",
        "requester_name": "Kenji Watanabe",
        "requester_email": "kenji@example.jp",
        "tags": "",
    },
    {
        "ticket_id": 10426,
        "subject": "How do I add a teammate?",
        "description": "How do I invite another person on my team to the workspace?",
        "requester_name": "Sam Ortiz",
        "requester_email": "sam@example.com",
        "tags": "",
    },
]
