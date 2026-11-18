import csv
import json
from pathlib import Path

FIXTURES_DIR = Path("fixtures")

# 10 Fixture Groups: 2 in pilot (8 files), 8 in eval (32 files) = 40 fixtures total
FIXTURE_GROUPS = [
    {
        "group_id": "grp01_cookie_banner",
        "partition": "pilot",
        "domain": "Cookie Consent Banner",
        "headline": "We Value Your Privacy",
        "body": "We use cookies to personalize content, serve promotional ads, and analyze traffic.",
        "accept_text": "Accept All Cookies",
        "neutral_decline": "Reject Non-Essential",
        "shame_decline": "No thanks, I want a broken browsing experience",
        "marketing_text": "Share my browsing activity with advertising partners for targeted promotions",
    },
    {
        "group_id": "grp02_newsletter_modal",
        "partition": "pilot",
        "domain": "E-Commerce Discount Popup",
        "headline": "Unlock 20% Off Your First Order",
        "body": "Join our VIP list for instant savings and seasonal flash deals.",
        "accept_text": "Claim My 20% Discount",
        "neutral_decline": "No Thanks",
        "shame_decline": "No thanks, I prefer paying full price",
        "marketing_text": "Send me daily promotional offers, partner coupons, and marketing emails",
    },
    {
        "group_id": "grp03_checkout_upsell",
        "partition": "eval",
        "domain": "Checkout Protection Upsell",
        "headline": "Protect Your Order Against Damage",
        "body": "Add priority replacement coverage for only $4.99 before completing checkout.",
        "accept_text": "Add Order Protection",
        "neutral_decline": "Continue Without Protection",
        "shame_decline": "No, I accept full financial risk if my package is lost",
        "marketing_text": "Automatically enroll me in sponsor product alerts and promotional newsletters",
    },
    {
        "group_id": "grp04_trial_cancel",
        "partition": "eval",
        "domain": "Subscription Retention Dialog",
        "headline": "Before You Cancel Your Membership...",
        "body": "Keep unlimited access to member-only perks and priority support.",
        "accept_text": "Keep My Membership",
        "neutral_decline": "Cancel Subscription",
        "shame_decline": "Yes, I want to give up all my saved benefits",
        "marketing_text": "Keep sending me promotional win-back discounts and partner marketing messages",
    },
    {
        "group_id": "grp05_account_signup",
        "partition": "eval",
        "domain": "Account Registration Form",
        "headline": "Create Your Free Store Account",
        "body": "Track orders faster and manage your saved delivery addresses.",
        "accept_text": "Complete Registration",
        "neutral_decline": "Skip For Now",
        "shame_decline": "No thanks, I hate convenient checkout",
        "marketing_text": "Subscribe me to weekly marketing blasts and third-party promotional deals",
    },
    {
        "group_id": "grp06_flash_sale_modal",
        "partition": "eval",
        "domain": "Flash Sale Countdown Popup",
        "headline": "Wait! Extra 15% Off Expires Soon",
        "body": "Apply this limited-time voucher to everything currently in your cart.",
        "accept_text": "Apply 15% Voucher",
        "neutral_decline": "Close Offer",
        "shame_decline": "I don't like saving money on my order",
        "marketing_text": "Sign me up for SMS and email marketing promotions",
    },
    {
        "group_id": "grp07_shipping_upgrade",
        "partition": "eval",
        "domain": "Delivery Speed Selection",
        "headline": "Upgrade to Express Priority Delivery",
        "body": "Get your items delivered tomorrow with guaranteed handling.",
        "accept_text": "Upgrade to Express",
        "neutral_decline": "Keep Standard Shipping",
        "shame_decline": "No, I enjoy waiting longer for my deliveries",
        "marketing_text": "Send promotional partner offers and seasonal catalog mailings",
    },
    {
        "group_id": "grp08_paywall_digest",
        "partition": "eval",
        "domain": "News Briefing Modal",
        "headline": "Stay Informed With Morning Headlines",
        "body": "Get curated breaking stories delivered straight to your inbox.",
        "accept_text": "Subscribe Free",
        "neutral_decline": "Maybe Later",
        "shame_decline": "No thanks, I prefer staying uninformed about current events",
        "marketing_text": "Include sponsored partner newsletters and promotional announcements",
    },
    {
        "group_id": "grp09_member_perks",
        "partition": "eval",
        "domain": "Loyalty Rewards Prompt",
        "headline": "Activate Double Points Today",
        "body": "Earn 2x reward points on every purchase this month.",
        "accept_text": "Activate Rewards",
        "neutral_decline": "Decline Offer",
        "shame_decline": "No, I choose to throw away free reward points",
        "marketing_text": "Opt me into promotional partner campaigns and marketing offers",
    },
    {
        "group_id": "grp10_app_access",
        "partition": "eval",
        "domain": "Digital Pass Modal",
        "headline": "Unlock Exclusive Member Pricing",
        "body": "Access lower rates across 500+ featured brands immediately.",
        "accept_text": "Unlock Member Pricing",
        "neutral_decline": "Continue as Guest",
        "shame_decline": "No thanks, overpaying doesn't bother me",
        "marketing_text": "Send me promotional brand deals and marketing digests",
    },
]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>{title}</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      background: #eef1f5;
      color: #1f2328;
      margin: 0;
      padding: 40px;
    }}
    .modal {{
      background: #ffffff;
      border: 1px solid #d0d7de;
      border-radius: 10px;
      max-width: 560px;
      margin: 0 auto;
      padding: 28px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
    }}
    .top-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }}
    h1 {{ font-size: 20px; margin: 0; }}
    p {{ font-size: 14px; color: #424a53; line-height: 1.5; }}
    .consent-row {{
      margin: 18px 0;
      padding: 12px;
      background: #f6f8fa;
      border-radius: 6px;
      font-size: 13px;
    }}
    .actions {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-top: 20px;
      flex-wrap: wrap;
    }}
    .btn-accept {{
      background: #0b57d0;
      color: #ffffff;
      border: none;
      padding: 12px 22px;
      font-size: 15px;
      font-weight: bold;
      border-radius: 6px;
      cursor: pointer;
    }}
    .btn-decline-equal {{
      background: #ffffff;
      color: #1f2328;
      border: 1px solid #595959;
      padding: 12px 22px;
      font-size: 15px;
      border-radius: 6px;
      cursor: pointer;
    }}
    .decline-downplayed-accessible {{
      color: #595959; /* >= 7:1 contrast on #ffffff (passes WCAG AA) */
      font-size: 11px;
      text-decoration: underline;
      background: none;
      border: none;
      padding: 2px 4px;
    }}
    .decline-downplayed-lowcontrast {{
      color: #b8b8b8; /* ~1.98:1 contrast on #ffffff (fails WCAG 1.4.3) */
      font-size: 11px;
      text-decoration: none;
      background: none;
      border: none;
      padding: 2px 4px;
    }}
    .icon-btn {{
      width: 32px;
      height: 32px;
      border: 1px solid #8c959f;
      background: #f6f8fa;
      border-radius: 4px;
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <main>
    <section class="modal" role="dialog" aria-label="{domain}">
      <div class="top-bar">
        <h1>{headline}</h1>
        {top_right_control}
      </div>
      <p>{body}</p>
      <div class="consent-row">
        {checkbox_html}
      </div>
      <div class="actions">
        <button type="button" class="btn-accept">{accept_text}</button>
        {decline_html}
      </div>
    </section>
  </main>
</body>
</html>
"""


def build_all_fixtures():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []

    for grp in FIXTURE_GROUPS:
        gid = grp["group_id"]
        part = grp["partition"]

        variants = [
            # Variant 1: Normal controls + Accessibility-only controls (no deceptive patterns)
            {
                "variant_id": f"{gid}_v1_normal_a11y",
                "design_notes": "Normal accept/decline + unchecked valid checkbox + button-name violation",
                "top_right_control": '<button type="button" class="icon-btn"></button>',  # button-name violation
                "checkbox_html": (
                    f'<label for="{gid}_cb1"><input id="{gid}_cb1" type="checkbox" /> '
                    f'{grp["marketing_text"]}</label>'  # unchecked = Normal
                ),
                "decline_html": f'<button type="button" class="btn-decline-equal">{grp["neutral_decline"]}</button>',
            },
            # Variant 2: Deceptive pattern-only controls (all WCAG contrast & labels valid)
            {
                "variant_id": f"{gid}_v2_dp_only",
                "design_notes": "Preselected marketing consent (valid label) + confirmshaming/downplayed decline (valid contrast)",
                "top_right_control": '<button type="button" class="icon-btn" aria-label="Close dialog">X</button>',
                "checkbox_html": (
                    f'<label for="{gid}_cb2"><input id="{gid}_cb2" type="checkbox" checked /> '
                    f'{grp["marketing_text"]}</label>'  # DP-only: preselected_marketing_consent
                ),
                "decline_html": (
                    f'<a href="#decline" class="decline-downplayed-accessible">{grp["shame_decline"]}</a>'
                ),  # DP-only: confirmshaming + visually_downplayed_rejection (accessible contrast #595959)
            },
            # Variant 3: OVERLAP (color-contrast + confirmshaming/downplayed AND label + preselected consent)
            {
                "variant_id": f"{gid}_v3_overlap_contrast_label",
                "design_notes": "Overlap 1: low-contrast confirmshaming/downplayed link; Overlap 2: unlabeled preselected checkbox",
                "top_right_control": '<a href="#help" aria-label="Help">?</a>',
                "checkbox_html": (
                    f'<input type="checkbox" checked /> <span>{grp["marketing_text"]}</span>'
                ),  # OVERLAP: axe 'label' + preselected_marketing_consent
                "decline_html": (
                    f'<a href="#decline" class="decline-downplayed-lowcontrast">{grp["shame_decline"]}</a>'
                ),  # OVERLAP: axe 'color-contrast' + confirmshaming/visually_downplayed_rejection
            },
            # Variant 4: OVERLAP (visually_downplayed_rejection + color-contrast) + same-page non-overlap co-occurrence
            {
                "variant_id": f"{gid}_v4_overlap_downplayed",
                "design_notes": "Overlap: low-contrast visually downplayed neutral link + separate link-name violation",
                "top_right_control": '<a href="#info"></a>',  # link-name violation (Accessibility-only)
                "checkbox_html": (
                    f'<label for="{gid}_cb4"><input id="{gid}_cb4" type="checkbox" /> '
                    f'Remember my preference on this device</label>'  # Normal
                ),
                "decline_html": (
                    f'<a href="#decline" class="decline-downplayed-lowcontrast">{grp["neutral_decline"]}</a>'
                ),  # OVERLAP: axe 'color-contrast' + visually_downplayed_rejection
            },
        ]

        for v in variants:
            html_content = HTML_TEMPLATE.format(
                title=v["variant_id"],
                domain=grp["domain"],
                headline=grp["headline"],
                body=grp["body"],
                accept_text=grp["accept_text"],
                top_right_control=v["top_right_control"],
                checkbox_html=v["checkbox_html"],
                decline_html=v["decline_html"],
            )
            file_path = FIXTURES_DIR / f"{v['variant_id']}.html"
            file_path.write_text(html_content, encoding="utf-8")

            manifest.append(
                {
                    "sample_id": v["variant_id"],
                    "fixture_group": gid,
                    "partition": part,
                    "source_type": "fixture",
                    "domain": grp["domain"],
                    "file_path": str(file_path),
                    "design_notes": v["design_notes"],
                }
            )

    (FIXTURES_DIR / "fixtures_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with (FIXTURES_DIR / "fixtures_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
        writer.writeheader()
        writer.writerows(manifest)

    print(f"Generated {len(manifest)} controlled fixtures in '{FIXTURES_DIR}/'")
    print(f"  Pilot fixtures : {sum(1 for m in manifest if m['partition'] == 'pilot')}")
    print(f"  Eval fixtures  : {sum(1 for m in manifest if m['partition'] == 'eval')}")


if __name__ == "__main__":
    build_all_fixtures()