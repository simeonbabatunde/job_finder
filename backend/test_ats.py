import requests

def test_slug(company_name):
    slug = company_name.lower().replace(" ", "")
    # Try Greenhouse
    gh_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    gh_res = requests.get(gh_url)
    if gh_res.status_code == 200:
        print(f"Found Greenhouse for {company_name}: {gh_url}")
        return

    # Try Lever
    lv_url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    lv_res = requests.get(lv_url)
    if lv_res.status_code == 200:
        data = lv_res.json()
        if data:
            print(f"Found Lever for {company_name}: {lv_url}")
            return

    print(f"Could not find ATS for {company_name} by guessing slug '{slug}'")

test_slug("Stripe")
test_slug("Netflix")
test_slug("Figma")
test_slug("Airbnb")
