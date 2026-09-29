import streamlit as st

st.title("🎈 My new app")
st.write(
    "Let's start building! For help and inspiration, head over to [docs.streamlit.io](https://docs.streamlit.io/)."
)
import base64
import html
import json
import os
import re
import textwrap
from datetime import date
from io import BytesIO

import anthropic
import openai
import requests
import streamlit as st
from google import genai
from google.genai import types as genai_types
from PIL import Image, ImageDraw, ImageFont

# Local Settings Save File Path
CONFIG_FILE = "config.json"

# This is the TASK prompt (what to write about). [Keyword] is replaced with each topic at generation time.
DEFAULT_TASK_PROMPT = (
    "Write an SEO-optimized, highly engaging article in simple English about [Keyword]. Start with a strong, "
    "attention-grabbing intro (no heading above it). Then explain the topic thoroughly and in depth - like a "
    "knowledgeable human blogger teaching a curious reader, not a quick AI summary. Cover the 'why' and 'how' "
    "behind each point, not just a surface-level list. Use clear H2 and H3 headings, short paragraphs, bullet "
    "points where they genuinely help, and an HTML table when comparing structured data. Use an "
    "easy-to-understand, conversational tone. Avoid AI jargon and fluff."
)

# Style / formatting rules the user can tick on or off. These sit "under the hood" today - now exposed.
ADDITIONAL_RULES = {
    "html_format": {
        "label": "Output clean HTML (recommended - required for correct WordPress formatting)",
        "text": (
            "Return the article as clean HTML using <h2>, <h3>, <p>, <ul>, <li>, <strong>, <em>, and <table> "
            "tags where appropriate. Never use Markdown syntax anywhere in the body - no **bold**, no "
            "_italics_, no '- ' or '* ' bullet dashes, no '|' table pipes - use the equivalent HTML tags "
            "instead. Do not wrap the response in <html>, <head>, <body> tags or code fences (```)."
        ),
        "default": True,
    },
    "depth_and_examples": {
        "label": "Explain concepts deeply with real examples (not a shallow AI summary)",
        "text": (
            "Don't just skim the surface - explain the reasoning and mechanics behind each point (the 'why' "
            "and 'how'), and include concrete examples, numbers, or scenarios where relevant, the way an "
            "experienced blogger teaches a reader who wants to genuinely understand the topic, not just get a "
            "quick listicle."
        ),
        "default": True,
    },
    "no_h1_duplicate": {
        "label": "Don't repeat the title or add an H1 in the body (recommended)",
        "text": (
            "Do not include the article title anywhere in the body and do not use an <h1> tag - WordPress "
            "already renders the post title separately."
        ),
        "default": True,
    },
    "no_intro_heading": {
        "label": "No heading above the intro paragraph (recommended)",
        "text": (
            "Start the article with a short introductory paragraph and do NOT put any heading - no H2, H3, or "
            "otherwise - above it or as its label. The very first heading in the article should only appear "
            "after the introduction, marking the start of the first main section."
        ),
        "default": True,
    },
    "faqs_conclusion": {
        "label": "Include an FAQ section and a Conclusion at the end",
        "text": (
            "Near the end of the article, add a 'Frequently Asked Questions' H2 section with 3-5 relevant "
            "questions (each as an H3) and concise answers, followed by a short 'Conclusion' H2 section that "
            "summarizes the key takeaways."
        ),
        "default": True,
    },
    "avoid_cliches": {
        "label": "Avoid common AI clichés and filler phrases",
        "text": (
            'Avoid stock AI phrases such as "in today\'s fast-paced world", "dive into", "unlock", "landscape", '
            '"in conclusion", "moreover", "it is important to note", or similar filler.'
        ),
        "default": True,
    },
    "vary_sentences": {
        "label": "Vary sentence length for natural, human rhythm",
        "text": (
            "Vary sentence length on purpose: mix short, punchy sentences with longer ones. Prefer a shorter "
            "sentence when it says the same thing just as well."
        ),
        "default": True,
    },
    "short_paragraphs": {
        "label": "Keep paragraphs short and scannable",
        "text": "Keep paragraphs short (2-4 sentences) and easy to scan on a phone screen.",
        "default": True,
    },
    "current_context": {
        "label": "Ground the article in today's date / avoid inventing facts",
        "text": (
            "Today's date is {today}. Reflect the most recent, relevant context you have access to, and never "
            "invent statistics, records, quotes, injuries, or results you are not confident about."
        ),
        "default": True,
    },
    "tables_when_useful": {
        "label": "Use a table when comparing data (records, stats, odds)",
        "text": "Use an HTML <table> when comparing structured data such as fight records, stats, or odds, if it improves clarity.",
        "default": True,
    },
    "eat_seo": {
        "label": "Follow Google E-E-A-T / Helpful Content guidelines",
        "text": "Follow Google's E-E-A-T and Helpful Content Guidelines: demonstrate experience, expertise, authority and trustworthiness.",
        "default": True,
    },
}

# Tone presets - "Human Blogger" and "Conversational" merged into one, per request
TONE_PRESETS = {
    "Human Blogger & Conversational (default)": (
        "Tone: write like a genuine human blogger talking directly to the reader - personal, warm, "
        "friendly and casual, using 'you', contractions, occasional first-person asides and natural rhythm, "
        "like a real person typed it in one sitting, not a formal press release."
    ),
    "Professional": (
        "Tone: polished, formal, third-person journalistic tone suitable for a mainstream sports outlet. "
        "No slang, no first-person asides, but still warm and readable."
    ),
    "SEO Optimized": (
        "Tone: scannable and search-intent driven - short paragraphs, keyword-relevant subheadings, and natural "
        "keyword placement early in the article, without sacrificing readability or sounding keyword-stuffed."
    ),
    "Humorous": (
        "Tone: witty and playful, with light jokes and one-liners where appropriate, while staying accurate and "
        "respectful. Do not force jokes into serious injury, tragedy, or controversy topics."
    ),
    "Storytelling / Narrative": (
        "Tone: open with a vivid scene or anecdote, build a narrative arc through the piece, and use descriptive, "
        "sensory language before moving into analysis."
    ),
    "Analytical / Expert Breakdown": (
        "Tone: write like a seasoned analyst or coach - confident, data-informed opinions, technique and "
        "matchup breakdowns, and strategic framing."
    ),
    "News / Journalistic": (
        "Tone: inverted-pyramid news style - lead with the most newsworthy fact, stay factual and concise, "
        "minimal editorializing, short punchy paragraphs."
    ),
}

# Model lists, verified as of late September 2026:
# - Gemini: 2.5-flash was shut down June 17, 2026; 2.5-pro shuts down Oct 16, 2026 (already blocked
#   for new API keys) - both removed. Google has iterated heavily on the Flash line since (3.5 -> 3.8)
#   while the Pro tier is still topped by 3.1-pro-preview (no GA Pro successor yet).
# - Claude: current Anthropic lineup (this app's own model family).
# - OpenAI: GPT-6 family (Astra/Sol/Luna) launched Sept 3-22, 2026, replacing the GPT-5.x line.
#   gpt-4o-mini kept as a fallback in case an account doesn't have GPT-6 access yet.
MODEL_OPTIONS = {
    "gemini": [
        "gemini-3.8-flash",        # Newest Flash - top agentic/coding performance (Sep 2, 2026)
        "gemini-3.6-flash",        # Prior Flash refresh (Jul 21, 2026)
        "gemini-3.5-flash",        # GA flagship Flash (May 19, 2026), still very capable
        "gemini-3.1-pro-preview",  # Best available Pro-tier reasoning model (preview)
    ],
    "claude": [
        "claude-haiku-4-5-20251001",  # Fastest, lightweight
        "claude-sonnet-5",             # Balanced flagship model
        "claude-opus-5-5",             # Most powerful reasoning
        "claude-fable-5-1",            # Top-tier Mythos-class model, extra safety-hardened
    ],
    "openai": [
        "gpt-6-astra",   # Flagship - 1M+ context, top reasoning/agentic work (Sep 3, 2026)
        "gpt-6-sol",     # High-end, cost-efficient, near-Astra reliability
        "gpt-6-luna",    # Fast and very cheap, best for high-volume bulk generation
        "gpt-4o-mini",   # Legacy fallback if GPT-6 isn't enabled on your account yet
    ],
}

MAX_TITLE_LENGTH = 70  # Google generally truncates title tags beyond ~55-60 characters

# Known meta keys different SEO plugins use for the meta description.
# Note: Yoast SEO and All in One SEO do NOT expose these via REST by default - the site needs a
# small snippet (shown in the dashboard) to register the key with show_in_rest => true.
# Rank Math and SEOPress generally accept REST writes to these keys out of the box.
SEO_PLUGIN_META_KEYS = {
    "Yoast SEO": "_yoast_wpseo_metadesc",
    "Rank Math": "rank_math_description",
    "All in One SEO": "_aioseo_description",
    "SEOPress": "_seopress_titles_desc",
}


# ----------------------------- Config helpers -----------------------------
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)


config = load_config()

# Migrate old single-site config (wp_url/wp_user/wp_pass) into the new "sites" list
if "sites" not in config:
    config["sites"] = []
    if config.get("wp_url"):
        config["sites"].append(
            {
                "name": config.get("wp_url", "My Site").replace("https://", "").replace("http://", ""),
                "url": config.get("wp_url", ""),
                "user": config.get("wp_user", ""),
                "pass": config.get("wp_pass", ""),
            }
        )
    save_config(config)

if "sites" not in st.session_state:
    st.session_state.sites = config.get("sites", [])

# ----------------------------- Streamlit UI setup -----------------------------
st.set_page_config(page_title="Auto Poster Dashboard", page_icon="🚀", layout="wide")


# ----------------------------- Password gate -----------------------------
def get_secret(key):
    """Reads a value from Streamlit secrets (set in the Cloud dashboard, or a local
    .streamlit/secrets.toml that is never committed to git) without crashing if none exist."""
    try:
        return st.secrets.get(key)
    except Exception:
        return None


def check_password():
    """Simple password gate for the whole dashboard. The real password lives in Streamlit
    secrets or an environment variable - never in the code or config.json - so it's safe to
    put this app in a public repo or a public URL."""
    app_password = get_secret("APP_PASSWORD") or os.environ.get("APP_PASSWORD")

    if not app_password:
        # No password configured yet (e.g. local dev) - let it through without nagging.
        return True

    if st.session_state.get("authenticated"):
        return True

    st.title("🔒 Auto Poster Login")
    pwd_input = st.text_input("Password", type="password", key="login_pwd")
    if st.button("Log in"):
        if pwd_input == app_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


if not check_password():
    st.stop()

st.title("🚀 WP Auto-Poster Dashboard")

if os.environ.get("APP_PASSWORD") or get_secret("APP_PASSWORD"):
    if st.sidebar.button("🔓 Log out"):
        st.session_state["authenticated"] = False
        st.rerun()

# Sidebar: Credentials & API Settings
st.sidebar.header("⚙️ Configuration Settings")

default_provider = config.get("ai_provider", "gemini")
provider_options = ["gemini", "claude", "openai"]
provider_index = (
    provider_options.index(default_provider) if default_provider in provider_options else 0
)

ai_provider = st.sidebar.selectbox("Select AI Provider", provider_options, index=provider_index)

saved_model = config.get("selected_model")
model_list = MODEL_OPTIONS[ai_provider]
model_index = model_list.index(saved_model) if saved_model in model_list else 0

selected_model = st.sidebar.selectbox("Select Model Version", model_list, index=model_index)

gemini_key = st.sidebar.text_input(
    "Gemini API Key",
    value=get_secret("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or config.get("gemini_key", ""),
    type="password",
)
claude_key = st.sidebar.text_input(
    "Claude API Key",
    value=get_secret("CLAUDE_API_KEY") or os.environ.get("CLAUDE_API_KEY") or config.get("claude_key", ""),
    type="password",
)
openai_key = st.sidebar.text_input(
    "OpenAI API Key",
    value=get_secret("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or config.get("openai_key", ""),
    type="password",
)

# API Check Button
if st.sidebar.button("🔍 Test API Connection"):
    try:
        if ai_provider == "gemini":
            client = genai.Client(api_key=gemini_key)
            client.models.generate_content(model=selected_model, contents="Hi")
            st.sidebar.success("✅ Gemini API Connected Successfully!")
        elif ai_provider == "claude":
            client = anthropic.Anthropic(api_key=claude_key)
            client.messages.create(
                model=selected_model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}],
            )
            st.sidebar.success("✅ Claude API Connected Successfully!")
        elif ai_provider == "openai":
            client = openai.OpenAI(api_key=openai_key)
            client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": "Hi"}],
            )
            st.sidebar.success("✅ OpenAI API Connected Successfully!")
    except Exception as e:
        st.sidebar.error(f"❌ API Test Failed: {e}")

st.sidebar.markdown("---")

# ----------------------------- WordPress sites management -----------------------------
# Site selection happens BEFORE the writing prompt / image / meta sections below, since all of
# those are now saved per site (different niches need different prompts, colors, etc.).
st.sidebar.subheader("🌐 WordPress Websites")

site_names = [s["name"] for s in st.session_state.sites]

if site_names:
    active_site_name = st.sidebar.selectbox("Active Website", site_names)
    active_site = next(s for s in st.session_state.sites if s["name"] == active_site_name)
else:
    st.sidebar.info("No websites added yet. Add one below.")
    active_site_name = None
    active_site = None

site_key = active_site_name or "default"

with st.sidebar.expander("➕ Add / Edit Website"):
    edit_name = st.text_input("Website Nickname", value="" if not active_site else active_site["name"])
    edit_url = st.text_input(
        "WordPress URL", value="https://maincardmoney.com" if not active_site else active_site["url"]
    )
    edit_user = st.text_input("WP Username", value="" if not active_site else active_site["user"])
    edit_pass = st.text_input(
        "WP App Password", value="" if not active_site else active_site["pass"], type="password"
    )

    save_col, delete_col = st.columns(2)
    with save_col:
        if st.button("💾 Save Website"):
            if not edit_name or not edit_url:
                st.warning("Nickname and URL are required.")
            else:
                new_site = {"name": edit_name, "url": edit_url, "user": edit_user, "pass": edit_pass}
                existing = next((s for s in st.session_state.sites if s["name"] == edit_name), None)
                if existing:
                    existing.update(new_site)
                else:
                    st.session_state.sites.append(new_site)
                config["sites"] = st.session_state.sites
                save_config(config)
                st.success(f"Saved '{edit_name}'!")
                st.rerun()
    with delete_col:
        if active_site and st.button("🗑️ Delete Website"):
            st.session_state.sites = [s for s in st.session_state.sites if s["name"] != active_site["name"]]
            config["sites"] = st.session_state.sites
            save_config(config)
            st.success(f"Deleted '{active_site['name']}'.")
            st.rerun()


def test_wp_connection(site):
    """Checks WordPress REST API auth using the app password."""
    try:
        credentials = f"{site['user']}:{site['pass']}"
        token = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        headers = {"Authorization": f"Basic {token}"}
        endpoint = f"{site['url'].rstrip('/')}/wp-json/wp/v2/users/me"
        res = requests.get(endpoint, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return True, f"Connected as {data.get('name', site['user'])}"
        return False, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return False, str(e)


def fetch_wp_categories(site):
    """Fetches all categories from a WordPress site."""
    try:
        credentials = f"{site['user']}:{site['pass']}"
        token = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        headers = {"Authorization": f"Basic {token}"}
        endpoint = f"{site['url'].rstrip('/')}/wp-json/wp/v2/categories"
        categories = []
        page = 1
        while True:
            res = requests.get(
                endpoint, headers=headers, params={"per_page": 100, "page": page}, timeout=15
            )
            if res.status_code != 200:
                break
            batch = res.json()
            if not batch:
                break
            categories.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return categories
    except Exception:
        return []


def fetch_wp_all_posts_meta(site, per_page=100, max_pages=50):
    """Fetches slug + title for every post on the site, any status (published, draft, pending,
    future, private) - used to check which planned keywords have already been written about."""
    credentials = f"{site['user']}:{site['pass']}"
    token = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"Basic {token}"}
    endpoint = f"{site['url'].rstrip('/')}/wp-json/wp/v2/posts"
    results = []
    page = 1
    while page <= max_pages:
        try:
            res = requests.get(
                endpoint,
                headers=headers,
                params={
                    "per_page": per_page,
                    "page": page,
                    "status": "publish,future,draft,pending,private",
                    "context": "edit",
                    "_fields": "slug,title",
                },
                timeout=20,
            )
        except Exception:
            break
        if res.status_code != 200:
            break
        batch = res.json()
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            title_obj = item.get("title", {})
            if isinstance(title_obj, dict):
                title_text = title_obj.get("rendered") or title_obj.get("raw") or ""
            else:
                title_text = str(title_obj)
            title_text = html.unescape(re.sub(r"<[^>]+>", "", title_text))
            results.append({"slug": (item.get("slug") or "").lower(), "title": title_text.lower()})
        if len(batch) < per_page:
            break
        page += 1
    return results


def find_unposted_keywords(keywords, existing_posts):
    """Splits a keyword list into (already_posted, not_posted) by matching each keyword's slug
    (the same slug this tool assigns when posting) or a title-substring match against existing posts."""
    existing_slugs = {p["slug"] for p in existing_posts if p.get("slug")}
    existing_titles = [p["title"] for p in existing_posts if p.get("title")]
    posted, unposted = [], []
    for kw in keywords:
        kw_slug = slugify(kw)
        kw_lower = kw.strip().lower()
        is_posted = (kw_slug and kw_slug in existing_slugs) or any(kw_lower in t for t in existing_titles)
        (posted if is_posted else unposted).append(kw)
    return posted, unposted


if active_site:
    if st.sidebar.button("🔌 Test Connection to Active Website"):
        ok, msg = test_wp_connection(active_site)
        if ok:
            st.sidebar.success(f"✅ {msg}")
        else:
            st.sidebar.error(f"❌ {msg}")

st.sidebar.markdown("---")

# ----------------------------- Writing prompt (saved PER SITE) -----------------------------
prompt_heading = "✍️ Writing Prompt" + (f" — {active_site['name']}" if active_site else "")
st.sidebar.subheader(prompt_heading)
st.sidebar.caption(
    "Saved per website, so different niches (e.g. UFC vs. home/DIY) can each keep their own prompt."
    if active_site else "Add a website above to save a prompt specific to it."
)

default_task_prompt = (active_site or {}).get("task_prompt") or config.get("system_prompt", DEFAULT_TASK_PROMPT)
custom_prompt = st.sidebar.text_area(
    "Task Prompt - use [Keyword] as a placeholder, it's replaced with each topic automatically",
    value=default_task_prompt,
    height=160,
    key=f"prompt_{site_key}",
)
prompt_cols = st.sidebar.columns(2)
with prompt_cols[0]:
    save_prompt_label = f"💾 Save for '{active_site['name']}'" if active_site else "💾 Save Prompt"
    if st.button(save_prompt_label):
        if active_site:
            active_site["task_prompt"] = custom_prompt
            config["sites"] = st.session_state.sites
        else:
            config["system_prompt"] = custom_prompt
        save_config(config)
        st.sidebar.success("Prompt saved!")
with prompt_cols[1]:
    if st.button("↩️ Reset to Default"):
        custom_prompt = DEFAULT_TASK_PROMPT
        if active_site:
            active_site["task_prompt"] = DEFAULT_TASK_PROMPT
            config["sites"] = st.session_state.sites
        else:
            config["system_prompt"] = DEFAULT_TASK_PROMPT
        save_config(config)
        st.rerun()

with st.sidebar.expander("🧩 Advanced Writing Rules (tick to include)"):
    saved_rule_toggles = config.get("rule_toggles", {})
    rule_states = {}
    for rule_key, rule in ADDITIONAL_RULES.items():
        rule_states[rule_key] = st.checkbox(
            rule["label"],
            value=saved_rule_toggles.get(rule_key, rule["default"]),
            key=f"rule_{rule_key}",
        )
    if st.button("💾 Save Rule Selections"):
        config["rule_toggles"] = rule_states
        save_config(config)
        st.success("Rule selections saved!")

use_web_search = st.sidebar.checkbox(
    "🔎 Use live web search for up-to-date facts (Claude & Gemini only)",
    value=config.get("use_web_search", True),
)

st.sidebar.markdown("---")

# ----------------------------- Featured image settings (saved PER SITE) -----------------------------
st.sidebar.subheader("🖼️ Featured Image")
generate_image = st.sidebar.checkbox(
    "Generate a featured image with the keyword centered",
    value=config.get("generate_image", True),
)

default_bg = (active_site or {}).get("img_bg_color", "#141414")
default_text = (active_site or {}).get("img_text_color", "#FFFFFF")
default_accent = (active_site or {}).get("img_accent_color", "#E4032E")

img_bg_color = st.sidebar.color_picker("Background color", value=default_bg, key=f"bg_{site_key}")
img_text_color = st.sidebar.color_picker("Text color", value=default_text, key=f"text_{site_key}")
img_accent_color = st.sidebar.color_picker("Accent bar color", value=default_accent, key=f"accent_{site_key}")

if active_site:
    if st.sidebar.button(f"💾 Save These Colors for '{active_site['name']}'"):
        active_site["img_bg_color"] = img_bg_color
        active_site["img_text_color"] = img_text_color
        active_site["img_accent_color"] = img_accent_color
        config["sites"] = st.session_state.sites
        save_config(config)
        st.sidebar.success(f"Image colors saved for '{active_site['name']}'!")
else:
    st.sidebar.caption("Add a website above to save its own featured-image colors.")

st.sidebar.markdown("---")

# ----------------------------- Meta description settings (saved PER SITE) -----------------------------
st.sidebar.subheader("📄 SEO Meta Description")
st.sidebar.caption("Generated separately from the article and sent as post metadata - it never appears in the body.")

default_meta_enabled = (active_site or {}).get("meta_desc_enabled", True)
default_meta_plugin = (active_site or {}).get("meta_desc_plugin", "Yoast SEO")
default_meta_custom_key = (active_site or {}).get("meta_desc_custom_key", "")
default_meta_len = int((active_site or {}).get("meta_desc_max_len", 155))

generate_meta_description_flag = st.sidebar.checkbox(
    "Generate & set an SEO meta description",
    value=default_meta_enabled,
    key=f"meta_enabled_{site_key}",
)

meta_plugin_options = list(SEO_PLUGIN_META_KEYS.keys()) + ["Custom Meta Key"]
meta_plugin_index = meta_plugin_options.index(default_meta_plugin) if default_meta_plugin in meta_plugin_options else 0
meta_plugin_choice = st.sidebar.selectbox(
    "SEO Plugin on this site", meta_plugin_options, index=meta_plugin_index, key=f"meta_plugin_{site_key}"
)

if meta_plugin_choice == "Custom Meta Key":
    custom_meta_key_input = st.sidebar.text_input(
        "Custom meta key", value=default_meta_custom_key, key=f"meta_customkey_{site_key}"
    )
    resolved_meta_key = custom_meta_key_input
else:
    custom_meta_key_input = default_meta_custom_key
    resolved_meta_key = SEO_PLUGIN_META_KEYS[meta_plugin_choice]

meta_desc_max_len = st.sidebar.slider(
    "Meta description max length (characters)",
    min_value=120,
    max_value=160,
    value=default_meta_len if 120 <= default_meta_len <= 160 else 155,
    key=f"meta_len_{site_key}",
)

if meta_plugin_choice in ("Yoast SEO", "All in One SEO"):
    with st.sidebar.expander("⚠️ Needed for Yoast/AIOSEO to accept this via REST"):
        st.caption(
            f"{meta_plugin_choice} hides its meta description field from the REST API by default. "
            f"Ask your developer to add this snippet (as a small plugin or in a code snippets plugin) so "
            f"'{resolved_meta_key}' can be set when posts are created:"
        )
        st.code(
            "add_action('init', function () {\n"
            f"    register_post_meta('post', '{resolved_meta_key}', [\n"
            "        'show_in_rest'  => true,\n"
            "        'single'        => true,\n"
            "        'type'          => 'string',\n"
            "        'auth_callback' => function () { return current_user_can('edit_posts'); },\n"
            "    ]);\n"
            "});",
            language="php",
        )

if active_site:
    if st.sidebar.button(f"💾 Save Meta Description Settings for '{active_site['name']}'"):
        active_site["meta_desc_enabled"] = generate_meta_description_flag
        active_site["meta_desc_plugin"] = meta_plugin_choice
        active_site["meta_desc_custom_key"] = custom_meta_key_input
        active_site["meta_desc_max_len"] = meta_desc_max_len
        config["sites"] = st.session_state.sites
        save_config(config)
        st.sidebar.success(f"Meta description settings saved for '{active_site['name']}'!")
else:
    st.sidebar.caption("Add a website above to save its own meta description settings.")

if st.sidebar.button("💾 Save All Other Settings"):
    config.update(
        {
            "ai_provider": ai_provider,
            "selected_model": selected_model,
            "gemini_key": gemini_key,
            "claude_key": claude_key,
            "openai_key": openai_key,
            "rule_toggles": rule_states,
            "sites": st.session_state.sites,
            "use_web_search": use_web_search,
            "generate_image": generate_image,
        }
    )
    save_config(config)
    st.sidebar.success("Settings saved successfully!")

st.sidebar.markdown("---")

# ----------------------------- Backup / restore (protects against ephemeral hosting disk) -----------------------------
with st.sidebar.expander("📦 Backup / Restore All Settings"):
    st.caption(
        "Many free hosts wipe local files on every restart or redeploy, which would erase your sites, "
        "prompts, and keys. Download a backup after setting things up, and restore it if that happens. "
        "⚠️ This file holds your API keys and WordPress passwords in plain text - keep it private and "
        "never commit it to a public repo."
    )
    st.download_button(
        "⬇️ Download Backup",
        data=json.dumps(config, indent=2),
        file_name="auto_poster_config_backup.json",
        mime="application/json",
    )
    uploaded_backup = st.file_uploader("Restore from a backup file", type="json", key="restore_backup_upload")
    if uploaded_backup is not None and st.button("♻️ Apply Restored Backup"):
        try:
            restored = json.load(uploaded_backup)
            if not isinstance(restored, dict):
                raise ValueError("That file doesn't look like a valid backup.")
            save_config(restored)
            st.success("Backup restored! Reloading...")
            st.rerun()
        except Exception as e:
            st.error(f"Couldn't restore that backup: {e}")


# ----------------------------- Helpers: slug, title, HTML cleanup -----------------------------
def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


TITLE_STOPWORDS = {
    "a", "an", "the", "for", "of", "in", "on", "to", "and", "or", "but", "with", "by", "at", "as",
    "that", "which", "is", "are", "was", "were", "this", "these", "those", "from", "into", "onto",
}


def _strip_dangling_words(words):
    """Drops leading/trailing filler words (a, for, the, with, ...) so a trimmed phrase never ends
    or starts on a dangling preposition/article like '...Naturally for a' or 'for How to...'."""
    words = list(words)
    while words and words[-1].lower().strip(".,!?:;-") in TITLE_STOPWORDS:
        words.pop()
    while words and words[0].lower().strip(".,!?:;-") in TITLE_STOPWORDS:
        words.pop(0)
    return words


def build_title(keyword, extra_words, max_len):
    """Builds the final title as: keyword + a short, natural suffix - never words in front of the
    keyword, and never a dangling connector word left hanging at either end after trimming."""
    keyword = keyword.strip()
    suffix_words = extra_words.strip().strip('"').strip("'").split() if extra_words else []

    while True:
        cleaned_suffix = _strip_dangling_words(suffix_words)
        candidate = f"{keyword} {' '.join(cleaned_suffix)}".strip() if cleaned_suffix else keyword
        if len(candidate) <= max_len:
            return candidate
        if not suffix_words:
            break
        suffix_words = suffix_words[:-1]

    # The keyword alone is still too long - trim it as a last resort, same dangling-word safety net
    kw_words = keyword.split(" ")
    while len(kw_words) > 1 and len(" ".join(kw_words)) > max_len:
        kw_words = kw_words[:-1]
    cleaned = _strip_dangling_words(kw_words)
    return " ".join(cleaned) if cleaned else " ".join(kw_words)


def _convert_markdown_bold_italic(text):
    """Some models slip into Markdown even when told not to. Convert what leaks through into HTML
    so it renders correctly in WordPress instead of showing literal asterisks."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    return text


def _convert_markdown_bullets(text):
    """Turns stray '- item' / '* item' / '– item' lines into a proper <ul><li> list."""
    lines = text.split("\n")
    output, buffer = [], []
    bullet_re = re.compile(r"^\s*[-\u2013*]\s+(.+)$")

    def flush():
        if buffer:
            output.append("<ul>" + "".join(f"<li>{item}</li>" for item in buffer) + "</ul>")
            buffer.clear()

    for line in lines:
        m = bullet_re.match(line)
        if m and not line.strip().startswith("<"):
            buffer.append(m.group(1).strip())
        else:
            flush()
            output.append(line)
    flush()
    return "\n".join(output)


def _convert_markdown_tables(text):
    """Turns a stray Markdown pipe-table into a real HTML <table>."""
    lines = text.split("\n")
    output, i = [], 0
    row_re = re.compile(r"^\s*\|(.+)\|\s*$")
    sep_re = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")

    while i < len(lines):
        line = lines[i]
        if row_re.match(line) and i + 1 < len(lines) and sep_re.match(lines[i + 1]) and "-" in lines[i + 1]:
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and row_re.match(lines[i]):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            html = "<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in header) + "</tr></thead><tbody>"
            for row in rows:
                html += "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
            html += "</tbody></table>"
            output.append(html)
        else:
            output.append(line)
            i += 1
    return "\n".join(output)


def sanitize_stray_markdown(text):
    text = _convert_markdown_tables(text)
    text = _convert_markdown_bold_italic(text)
    text = _convert_markdown_bullets(text)
    return text


def clean_html(text, title, strip_intro_heading=True):
    """Strips code fences and removes any leading H1 / duplicated title from generated content.
    Also strips a stray heading sitting above the intro paragraph, if strip_intro_heading is on,
    and converts any Markdown the model used anyway into real HTML."""
    text = text.replace("```html", "").replace("```", "").strip()
    text = re.sub(r"^\s*<h1[^>]*>.*?</h1>\s*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        rf"^\s*<p>\s*{re.escape(title.strip())}\s*</p>\s*",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if strip_intro_heading:
        # If the article still opens with a heading (the model ignored the "no intro heading"
        # rule), drop just that one heading so the article leads with plain intro text instead.
        text = re.sub(r"^\s*<h[23][^>]*>.*?</h[23]>\s*", "", text, flags=re.IGNORECASE | re.DOTALL, count=1)
    text = sanitize_stray_markdown(text)
    return text.strip()


def apply_keyword_placeholder(prompt_template, topic):
    if re.search(r"\[keyword\]", prompt_template, flags=re.IGNORECASE):
        return re.sub(r"\[keyword\]", topic, prompt_template, flags=re.IGNORECASE)
    return f"{prompt_template.strip()}\n\nTopic: {topic}"


def build_style_system_prompt(tone_label, rules_selected):
    tone_instruction = TONE_PRESETS.get(tone_label, "")
    rule_lines = []
    for rule_key, rule in ADDITIONAL_RULES.items():
        if rules_selected.get(rule_key, rule["default"]):
            text = rule["text"]
            if "{today}" in text:
                text = text.format(today=date.today().strftime("%B %d, %Y"))
            rule_lines.append(f"- {text}")
    rules_block = "\n".join(rule_lines)
    parts = [p for p in [tone_instruction, ("Additional rules:\n" + rules_block) if rules_block else ""] if p]
    return "\n\n".join(parts)


# ----------------------------- Featured image generation -----------------------------
def load_font(size):
    candidate_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "arialbd.ttf",
    ]
    for path in candidate_fonts:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def wrap_to_width(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_featured_image(keyword, bg_color="#141414", text_color="#FFFFFF", accent_color="#E4032E",
                             width=1200, height=630):
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    bar_h = 18
    draw.rectangle([0, 0, width, bar_h], fill=accent_color)
    draw.rectangle([0, height - bar_h, width, height], fill=accent_color)

    max_width_px = width - 160
    max_height_px = height - 200
    text = keyword.strip().upper()

    font_size = 100
    font, lines = None, [text]
    while font_size >= 28:
        font = load_font(font_size)
        lines = wrap_to_width(draw, text, font, max_width_px)
        line_bboxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        line_heights = [(b[3] - b[1]) for b in line_bboxes]
        total_height = int(sum(line_heights) * 1.35)
        max_line_width = max((b[2] - b[0]) for b in line_bboxes)
        if total_height <= max_height_px and max_line_width <= max_width_px and len(lines) <= 4:
            break
        font_size -= 6

    line_heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1]
                     for line in lines]
    spacing = int(font_size * 0.35)
    total_text_height = sum(line_heights) + spacing * (len(lines) - 1)
    y = (height - total_text_height) // 2

    for line, line_h in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        draw.text((x, y), line, font=font, fill=text_color)
        y += line_h + spacing

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()


def upload_featured_image(site, image_bytes, filename, alt_text=""):
    credentials = f"{site['user']}:{site['pass']}"
    token = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    endpoint = f"{site['url'].rstrip('/')}/wp-json/wp/v2/media"
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "image/png",
    }
    try:
        res = requests.post(endpoint, headers=headers, data=image_bytes, timeout=60)
        if res.status_code in (200, 201):
            media = res.json()
            media_id = media.get("id")
            if alt_text and media_id:
                try:
                    requests.post(
                        f"{endpoint}/{media_id}",
                        headers={"Authorization": f"Basic {token}"},
                        json={"alt_text": alt_text},
                        timeout=30,
                    )
                except Exception:
                    pass
            return media_id, None
        return None, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as e:
        return None, str(e)


# ----------------------------- Content generation -----------------------------
TITLE_SUFFIX_INSTRUCTION = (
    "I'm building an SEO title that starts with this exact keyword phrase: '{topic}'. Give me ONLY 2 to 4 "
    "short, natural words to add AFTER the keyword so the full title (keyword + your words) reads as one "
    "compelling, grammatically complete headline and stays within about {max_len} characters total. "
    "Return ONLY those extra words - no quotes, no leading punctuation, don't repeat the keyword itself, "
    "and don't return a full sentence."
)

META_DESCRIPTION_INSTRUCTION = (
    "Write a compelling SEO meta description for an article about the keyword: '{topic}'. The article's title "
    "is '{title}'. Naturally include the keyword. It MUST be {max_len} characters or fewer - shorter is fine, "
    "longer is not. Write it as one or two plain sentences. Return ONLY the meta description text - no quotes, "
    "no hashtags, no markdown."
)


def enforce_char_limit(text, max_len):
    text = text.strip().strip('"').strip("'")
    if len(text) <= max_len:
        return text
    trimmed = text[:max_len].rsplit(" ", 1)[0].rstrip(" ,.-")
    return trimmed if trimmed else text[:max_len]


def generate_meta_description(provider, model_name, topic, title, max_len):
    """Generates a short SEO meta description using whichever provider/model is selected.
    Kept separate from the article body - it's only ever sent as WordPress post metadata."""
    prompt = META_DESCRIPTION_INSTRUCTION.format(topic=topic, title=title, max_len=max_len)
    try:
        if provider == "gemini":
            client = genai.Client(api_key=gemini_key)
            res = client.models.generate_content(model=model_name, contents=prompt)
            raw = res.text
        elif provider == "claude":
            client = anthropic.Anthropic(api_key=claude_key)
            res = client.messages.create(
                model=model_name, max_tokens=150, messages=[{"role": "user", "content": prompt}]
            )
            raw = res.content[0].text
        else:
            client = openai.OpenAI(api_key=openai_key)
            res = client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": prompt}])
            raw = res.choices[0].message.content
        return enforce_char_limit(raw, max_len)
    except Exception:
        return None


def estimate_max_tokens(word_count):
    """Rough output-token budget for a target word count, with room for HTML markup overhead."""
    return max(1500, min(14000, int(word_count * 2.2) + 1000))


def length_instruction(word_count):
    return (
        f"Aim for at least {word_count} words - treat this as a floor, not a ceiling. Go longer than that if "
        f"the topic genuinely needs more explanation, examples, or detail to be thorough and helpful. Don't pad "
        f"with filler or repeat yourself just to add length, but don't cut real explanation short either - "
        f"depth and completeness matter more than hitting an exact number."
    )


def generate_article_gemini(topic, model_name, style_prompt, task_prompt, use_search, word_count, strip_intro_heading):
    client = genai.Client(api_key=gemini_key)

    title_res = client.models.generate_content(
        model=model_name,
        contents=TITLE_SUFFIX_INSTRUCTION.format(topic=topic, max_len=MAX_TITLE_LENGTH),
    )
    title = build_title(topic, title_res.text.strip(), MAX_TITLE_LENGTH)

    full_contents = (
        f"{task_prompt}\n\nThe article's title is already: '{title}' — do not repeat it or add an H1 in the body.\n\n"
        f"{length_instruction(word_count)}"
    )

    gen_config_kwargs = {"max_output_tokens": estimate_max_tokens(word_count)}
    if style_prompt:
        gen_config_kwargs["system_instruction"] = style_prompt

    if use_search:
        try:
            cfg = genai_types.GenerateContentConfig(
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())], **gen_config_kwargs
            )
            response = client.models.generate_content(model=model_name, contents=full_contents, config=cfg)
        except Exception:
            cfg = genai_types.GenerateContentConfig(**gen_config_kwargs)
            response = client.models.generate_content(model=model_name, contents=full_contents, config=cfg)
    else:
        cfg = genai_types.GenerateContentConfig(**gen_config_kwargs)
        response = client.models.generate_content(model=model_name, contents=full_contents, config=cfg)

    content = clean_html(response.text, title, strip_intro_heading=strip_intro_heading)
    return title, content


def generate_article_claude(topic, model_name, style_prompt, task_prompt, use_search, word_count, strip_intro_heading):
    client = anthropic.Anthropic(api_key=claude_key)

    title_res = client.messages.create(
        model=model_name,
        max_tokens=100,
        messages=[{"role": "user", "content": TITLE_SUFFIX_INSTRUCTION.format(topic=topic, max_len=MAX_TITLE_LENGTH)}],
    )
    title = build_title(topic, title_res.content[0].text.strip(), MAX_TITLE_LENGTH)

    user_message = (
        f"{task_prompt}\n\nThe article's title is already: '{title}' — do not repeat it or add an H1 in the body.\n\n"
        f"{length_instruction(word_count)}"
    )

    def call_claude(with_search):
        kwargs = dict(
            model=model_name,
            max_tokens=estimate_max_tokens(word_count),
            system=style_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        if with_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
        return client.messages.create(**kwargs)

    if use_search:
        try:
            response = call_claude(True)
        except Exception:
            response = call_claude(False)
    else:
        response = call_claude(False)

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    content = clean_html("\n".join(text_parts), title, strip_intro_heading=strip_intro_heading)
    return title, content


def openai_chat_completion(client, model_name, messages, token_budget=None):
    """Newer OpenAI models (the GPT-6 family, o-series, etc.) require 'max_completion_tokens'
    instead of the older 'max_tokens' - and some older models reject whichever one they don't
    expect. Try the modern parameter first and transparently retry with the other one if the API
    says it's unsupported, so this keeps working regardless of which model is selected."""
    if token_budget is None:
        return client.chat.completions.create(model=model_name, messages=messages)
    try:
        return client.chat.completions.create(
            model=model_name, messages=messages, max_completion_tokens=token_budget
        )
    except Exception as e:
        msg = str(e).lower()
        if "max_completion_tokens" in msg and "unsupported" in msg:
            return client.chat.completions.create(model=model_name, messages=messages, max_tokens=token_budget)
        raise


def generate_article_openai(topic, model_name, style_prompt, task_prompt, word_count, strip_intro_heading):
    client = openai.OpenAI(api_key=openai_key)

    title_res = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": TITLE_SUFFIX_INSTRUCTION.format(topic=topic, max_len=MAX_TITLE_LENGTH)}],
    )
    title = build_title(topic, title_res.choices[0].message.content.strip(), MAX_TITLE_LENGTH)

    user_message = (
        f"{task_prompt}\n\nThe article's title is already: '{title}' — do not repeat it or add an H1 in the body.\n\n"
        f"{length_instruction(word_count)}"
    )

    response = openai_chat_completion(
        client,
        model_name,
        messages=[
            {"role": "system", "content": style_prompt},
            {"role": "user", "content": user_message},
        ],
        token_budget=estimate_max_tokens(word_count),
    )
    content = clean_html(response.choices[0].message.content, title, strip_intro_heading=strip_intro_heading)
    return title, content


def post_to_wordpress(site, title, content, status="draft", category_ids=None, slug=None, featured_media=None,
                       meta_key=None, meta_description=None):
    credentials = f"{site['user']}:{site['pass']}"
    token = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }
    endpoint = f"{site['url'].rstrip('/')}/wp-json/wp/v2/posts"
    payload = {"title": title, "content": content, "status": status}
    if category_ids:
        payload["categories"] = category_ids
    if slug:
        payload["slug"] = slug
    if featured_media:
        payload["featured_media"] = featured_media
    if meta_key and meta_description:
        payload["meta"] = {meta_key: meta_description}

    res = requests.post(endpoint, headers=headers, json=payload, timeout=60)
    try:
        return res.status_code, res.json()
    except ValueError:
        return res.status_code, {"raw": res.text}


# ----------------------------- Main Dashboard Interface -----------------------------
st.subheader("📝 Generate & Post Article")

if not active_site:
    st.warning("Add a WordPress website in the sidebar before posting.")
else:
    st.caption(f"Posting to: **{active_site['name']}** ({active_site['url']})")

    categories = fetch_wp_categories(active_site) if active_site else []
    category_map = {c["name"]: c["id"] for c in categories}

    top_cols = st.columns(2)
    with top_cols[0]:
        if category_map:
            selected_categories = st.multiselect(
                "Categories (optional — leave empty for the site default)",
                options=list(category_map.keys()),
            )
        else:
            selected_categories = []
            st.caption("No categories found for this site (or connection not verified yet).")
    with top_cols[1]:
        tone_choice = st.selectbox("Article Tone", list(TONE_PRESETS.keys()), index=0)

    word_count = st.number_input(
        "Minimum word count per article",
        min_value=300,
        max_value=6000,
        value=1000,
        step=100,
        help=(
            "Treated as a floor, not a hard cap - the AI is told to go longer than this if the topic needs "
            "more depth or detail to be genuinely thorough. It won't pad with filler just to hit a number."
        ),
    )

    with st.expander(f"🗺️ Keyword Sitemap — Content Plan for '{active_site['name']}'"):
        st.caption(
            "Paste your full list of planned keywords here (one per line) and save it. Then use the check "
            "below to load only the ones not yet posted (published, drafted, or scheduled) into the topics "
            "box below."
        )
        sitemap_text = st.text_area(
            "Planned keywords for this site",
            value=active_site.get("keyword_sitemap", ""),
            height=180,
            key=f"sitemap_{site_key}",
        )
        sitemap_cols = st.columns(2)
        with sitemap_cols[0]:
            if st.button("💾 Save Keyword List"):
                active_site["keyword_sitemap"] = sitemap_text
                config["sites"] = st.session_state.sites
                save_config(config)
                st.success("Keyword list saved!")
        with sitemap_cols[1]:
            if st.button("🔍 Check & Load Non-Posted Keywords"):
                all_planned = [k.strip() for k in sitemap_text.split("\n") if k.strip()]
                if not all_planned:
                    st.warning("Paste some keywords above first.")
                else:
                    with st.spinner("Checking existing posts on this site..."):
                        existing_posts = fetch_wp_all_posts_meta(active_site)
                    already_posted, not_posted = find_unposted_keywords(all_planned, existing_posts)
                    st.session_state["topic_input_ta"] = "\n".join(not_posted)
                    st.success(
                        f"✅ {len(already_posted)} already posted (skipped) — "
                        f"📝 {len(not_posted)} new keyword(s) loaded into the box below."
                    )
                    if already_posted:
                        with st.expander(f"Already-posted keywords ({len(already_posted)}) - skipped"):
                            st.write("\n".join(already_posted))

    topic_input = st.text_area(
        "Enter Topics / Keywords (One per line for bulk post):",
        height=150,
        placeholder="UFC Fighter Joshua Van career analysis\nAlex Pereira vs Magomed Ankalaev preview",
        key="topic_input_ta",
    )

    post_status = st.radio("Post Status in WordPress:", ["draft", "publish"])

    if st.button("🚀 Run Auto Poster", type="primary"):
        if not topic_input.strip():
            st.warning("Please enter at least one topic!")
        else:
            topics = [t.strip() for t in topic_input.split("\n") if t.strip()]
            category_ids = [category_map[name] for name in selected_categories] if selected_categories else None
            style_system_prompt = build_style_system_prompt(tone_choice, rule_states)
            strip_intro_heading = rule_states.get("no_intro_heading", True)

            for topic in topics:
                st.info(f"Generating article for: **{topic}** using [{ai_provider.upper()} - {selected_model}]...")

                try:
                    task_prompt = apply_keyword_placeholder(custom_prompt, topic)

                    if ai_provider == "gemini":
                        title, content = generate_article_gemini(
                            topic, selected_model, style_system_prompt, task_prompt, use_web_search,
                            word_count, strip_intro_heading,
                        )
                    elif ai_provider == "claude":
                        title, content = generate_article_claude(
                            topic, selected_model, style_system_prompt, task_prompt, use_web_search,
                            word_count, strip_intro_heading,
                        )
                    else:
                        title, content = generate_article_openai(
                            topic, selected_model, style_system_prompt, task_prompt,
                            word_count, strip_intro_heading,
                        )

                    st.success(f"Generated Title ({len(title)} chars): {title}")

                    meta_description = None
                    if generate_meta_description_flag and resolved_meta_key:
                        meta_description = generate_meta_description(
                            ai_provider, selected_model, topic, title, meta_desc_max_len
                        )
                        if meta_description:
                            st.caption(f"📄 Meta description ({len(meta_description)} chars): {meta_description}")
                        else:
                            st.warning("Meta description generation failed - posting without one.")

                    slug = slugify(topic)

                    featured_media_id = None
                    if generate_image:
                        image_bytes = generate_featured_image(
                            topic,
                            bg_color=img_bg_color,
                            text_color=img_text_color,
                            accent_color=img_accent_color,
                        )
                        st.image(image_bytes, caption="Featured image preview", width=400)
                        featured_media_id, img_err = upload_featured_image(
                            active_site, image_bytes, f"{slug}.png", alt_text=topic
                        )
                        if img_err:
                            st.warning(f"Featured image upload failed: {img_err}")

                    status_code, response_data = post_to_wordpress(
                        active_site,
                        title,
                        content,
                        status=post_status,
                        category_ids=category_ids,
                        slug=slug,
                        featured_media=featured_media_id,
                        meta_key=resolved_meta_key if generate_meta_description_flag else None,
                        meta_description=meta_description,
                    )

                    if status_code in [200, 201]:
                        st.balloons()
                        st.success(f"✅ Successfully Posted to WP! [View Post]({response_data.get('link')})")
                    else:
                        st.error(f"❌ WordPress Error ({status_code}): {response_data}")

                except Exception as e:
                    st.error(f"Execution Error: {e}")
