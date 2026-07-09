import argparse
import sys
import os
import csv
import random
import pandas as pd
from time import sleep
from playwright.sync_api import sync_playwright, Page

# --- Paths adapted for Docker Volumes ---
INPUT_CSV = "leads.csv"
OUTPUT_CSV = "/app/output/linkedin_results.csv"
DEBUG_DIR = "/app/output/debug"

def is_logged_in(page: Page) -> bool:
    blocked = ("linkedin.com/login", "linkedin.com/checkpoint", "linkedin.com/authwall")
    return not any(x in page.url for x in blocked)

def dump_debug_state(page: Page, label: str):
    os.makedirs(DEBUG_DIR, exist_ok=True)
    page.screenshot(path=f"{DEBUG_DIR}/{label}.png", full_page=True)
    with open(f"{DEBUG_DIR}/{label}.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print(f"[debug] Saved screenshot + HTML for '{label}' -> {DEBUG_DIR}")
    for sel in ["[role='alert']", ".alert", "[id*='error']", "[class*='error']"]:
        loc = page.locator(sel)
        for i in range(loc.count()):
            try:
                text = loc.nth(i).inner_text().strip()
                if text:
                    print(f"[debug] {sel} -> {text!r}")
            except Exception:
                pass

def check_premium_and_activity(page: Page, activity_url: str) -> tuple[str, str]:
    page.goto(activity_url, wait_until="domcontentloaded", timeout=30000)

    if "login" in page.url.lower() or "challenge" in page.url.lower():
        raise Exception(f"LinkedIn killed session: {page.url}")

    page.wait_for_timeout(random.randint(3000, 7000))
    print(f"Current URL after goto: {page.url}")

    premium_svg = page.locator('svg[aria-label*="Premium member"]')
    premium_status = "premium member" if premium_svg.count() > 0 else "normal member"

    try:
        first_post = page.locator("div.fie-impression-container").first
        time_element = first_post.locator("span.update-components-actor__sub-description").first
        raw_text = time_element.inner_text().strip()
        activity_time = raw_text.split("•")[0].strip()
    except:
        activity_time = "No activity"

    return premium_status, activity_time

def create_output_csv():
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["Profile URL", "Type", "Last Activity"])

def append_result(profile_url, premium_status, activity_time):
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([profile_url, premium_status, activity_time])

def inject_stealth_scripts(page: Page):
    # Overwrites browser fingerprints to avoid detection
    page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)

def main():
    parser = argparse.ArgumentParser(description="Log into LinkedIn and Scrape via Docker")
    parser.add_argument("-u", "--username", required=True, help="LinkedIn email")
    parser.add_argument("-p", "--password", required=True, help="LinkedIn password")
    args = parser.parse_args()

    if not os.path.exists(INPUT_CSV):
        print(f"❌ Error: Input file '{INPUT_CSV}' not found.")
        sys.exit(1)

    create_output_csv()
    print("Reading leads.csv...")
    df = pd.read_csv(INPUT_CSV)
    df = df.dropna(subset=[df.columns[0], df.columns[1]])

    # URL normalization from your previous snippet
    profile_urls = [url.replace("http://", "https://") for url in df.iloc[:, 0].tolist()]
    activity_urls = [url.replace("http://", "https://") for url in df.iloc[:, 1].tolist()]
    print(f"Found {len(profile_urls)} profiles.")

    # In Docker, we save the profile to a specific directory we will mount
    user_data_dir = "/app/linkedin_profile"

    with sync_playwright() as p:
        print("Launching headless stealth browser context...")

        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        inject_stealth_scripts(page)

        print("Navigating to LinkedIn login gateway...")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        sleep(3)

        if is_logged_in(page) and "feed" in page.url:
            print("🎉 Already logged in via persistent session context!")
        else:
            print("Waiting for credentials fields to appear...")
            try:
                username_field = page.locator("input[autocomplete*='username']").last
                username_field.wait_for(state="visible", timeout=10000)
                username_field.fill(args.username)
                sleep(1.2)
                
                password_field = page.locator("input[autocomplete='current-password']").last
                password_field.fill(args.password)
                sleep(1)
            except Exception as e:
                print(f"❌ Target input fields missing. Current URL: {page.url}")
                context.close()
                sys.exit(1)

            print("Submitting login form...")
            submit_btn = page.locator("button[type='submit'], button:has-text('Sign in')").last
            submit_btn.click()
            sleep(5)

            if "checkpoint" in page.url or "challenge" in page.url:
                print("\n⚠️ CAPTCHA / 2FA DETECTED IN DOCKER!")
                print("Since you are in Docker and running headless, you cannot complete this visually.")
                dump_debug_state(page, "checkpoint")
                context.close()
                sys.exit(1)

            if not is_logged_in(page):
                print(f"\n❌ Login failed. Ended up on: {page.url}")
                dump_debug_state(page, "login_failure")
                context.close()
                sys.exit(1)
            
            print("\n🎉 Login successful! Session saved to mounted volume.")

        print("\n🚀 Starting the profile scanning process...")
        for profile_url, activity_url in zip(profile_urls, activity_urls):
            try:
                print(f"\nProcessing: {profile_url}")
                premium_status, activity_time = check_premium_and_activity(page, activity_url)

                print(f"-> Premium: {premium_status}")
                print(f"-> Activity: {activity_time}")

                append_result(profile_url, premium_status, activity_time)
                print("Status saved.")
                
            except Exception as e:
                print(f"❌ Failed to process profile: {profile_url}")
                print(f"Reason: {e}")

        context.close()
    print("\n✅ Run completed successfully.")

if __name__ == "__main__":
    main()