from playwright.sync_api import sync_playwright
import json
import pandas as pd
import csv
import os


RAW_COOKIE_FILE = "linkedin_export.json"
COOKIES_FILE = "linkedin_cookies.json"

INPUT_CSV = "leads.csv"
OUTPUT_CSV = "linkedin_results.csv"


def normalize_same_site(value):

    if not value:
        return "Lax"

    value = str(value).lower()

    mapping = {
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
        "no_restriction": "None",
        "unspecified": "Lax"
    }

    return mapping.get(value, "Lax")


def convert_cookies():

    with open(
        RAW_COOKIE_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        cookies = json.load(f)

    converted = []

    for c in cookies:

        try:

            converted.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "expires": int(
                    c.get(
                        "expirationDate",
                        -1
                    )
                ),
                "httpOnly": c.get(
                    "httpOnly",
                    False
                ),
                "secure": c.get(
                    "secure",
                    True
                ),
                "sameSite": normalize_same_site(
                    c.get(
                        "sameSite",
                        "Lax"
                    )
                )
            })

        except Exception as e:

            print(
                f"Skipping cookie: {e}"
            )

    with open(
        COOKIES_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            converted,
            f,
            indent=2
        )

    print(
        "Cookies converted"
    )


def load_cookies(context):

    with open(
        COOKIES_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        cookies = json.load(f)

    context.add_cookies(
        cookies
    )


def check_premium(
    page,
    profile_url
):

    page.goto(
        profile_url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    page.wait_for_timeout(
        4000
    )

    premium_svg = page.locator(
        'svg[aria-label*="Premium member"]'
    )

    if premium_svg.count() > 0:
        return "premium member"

    return "normal member"


def get_recent_activity_time(
    page,
    profile_url
):

    activity_url = (
        profile_url.rstrip("/")
        + "/recent-activity/reactions/"
    )

    page.goto(
        activity_url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    page.wait_for_timeout(
        5000
    )

    try:

        first_post = page.locator(
            "div.fie-impression-container"
        ).first

        time_element = first_post.locator(
            "span.update-components-actor__sub-description"
        ).first

        raw_text = (
            time_element
            .inner_text()
            .strip()
        )

        activity_time = (
            raw_text
            .split("•")[0]
            .strip()
        )

        return activity_time

    except:

        return "No activity"


def create_output_csv():

    if not os.path.exists(
        OUTPUT_CSV
    ):

        with open(
            OUTPUT_CSV,
            "w",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.writer(
                file
            )

            writer.writerow([
                "Profile URL",
                "Type",
                "Last Activity"
            ])


def append_result(
    profile_url,
    premium_status,
    activity_time
):

    with open(
        OUTPUT_CSV,
        "a",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(
            file
        )

        writer.writerow([
            profile_url,
            premium_status,
            activity_time
        ])


def main():

    convert_cookies()

    create_output_csv()

    print(
        "Reading leads.csv..."
    )

    df = pd.read_csv(
        INPUT_CSV
    )

    profile_urls = (
        df["Linkedin URL"]
        .dropna()
        .head(5)
        .tolist()
    )

    print(
        f"Found {len(profile_urls)} profiles"
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = (
            browser.new_context()
        )

        load_cookies(
            context
        )

        page = (
            context.new_page()
        )

        for profile_url in profile_urls:

            try:

                print(
                    "\nProcessing:"
                )

                print(
                    profile_url
                )

                premium_status = (
                    check_premium(
                        page,
                        profile_url
                    )
                )

                activity_time = (
                    get_recent_activity_time(
                        page,
                        profile_url
                    )
                )

                print(
                    f"Premium: {premium_status}"
                )

                print(
                    f"Activity: {activity_time}"
                )

                append_result(
                    profile_url,
                    premium_status,
                    activity_time
                )

                print(
                    "Saved"
                )

            except Exception as e:

                print(
                    f"Failed: {profile_url}"
                )

                print(e)

        browser.close()

    print(
        "\nDone"
    )


if __name__ == "__main__":
    main()