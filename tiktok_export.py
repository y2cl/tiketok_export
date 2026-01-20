import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime
import shutil
import re

MIN_PYTHON = (3, 8)
FILENAME_LENGTH = 10    # video filename
FOLDER_LENGTH = 50      # folder name max chars

# ------------------ Helper Functions ------------------

def check_python_version():
    if sys.version_info < MIN_PYTHON:
        sys.exit("❌ Python 3.8+ is required.")

def is_yt_dlp_installed():
    try:
        subprocess.run(["yt-dlp", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False

def install_yt_dlp():
    response = input("yt-dlp is not installed. Install it now? (y/n): ").lower()
    if response != "y":
        sys.exit("❌ yt-dlp is required.")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"], check=True)

def get_download_options():
    print("\nHow many videos do you want to download?")
    print("1) All videos")
    print("2) A specific number of recent videos")
    print("3) A date range")

    choice = input("Select an option (1/2/3): ").strip()
    if choice == "1":
        return []
    if choice == "2":
        count = input("Enter number of recent videos: ").strip()
        if not count.isdigit():
            sys.exit("❌ Invalid number.")
        return ["--playlist-end", count]
    if choice == "3":
        start = input("Start date (YYYY-MM-DD): ").strip()
        end = input("End date (YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(start, "%Y-%m-%d")
            datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            sys.exit("❌ Invalid date format.")
        return ["--dateafter", start.replace("-", ""), "--datebefore", end.replace("-", "")]
    sys.exit("❌ Invalid selection.")

def sanitize(text):
    """Remove invalid filesystem characters"""
    return "".join(c for c in text if c not in r'\/:*?"<>|').strip()

def extract_hashtags(description):
    """Extract hashtags from description using regex"""
    return " ".join(re.findall(r"#\w+", description)) if description else "(No hashtags)"

# ------------------ CSV Helpers ------------------

def load_existing_csv(csv_path):
    """Return a dict of title -> row data"""
    existing = {}
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        for line in lines[1:]:  # skip header
            parts = line.split(",")
            if parts:
                existing[parts[0].strip('"')] = parts
    return existing

def update_csv_row(csv_path, title, data):
    """Update Views/Likes/Comments in CSV for given title"""
    if not csv_path.exists():
        return
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    header = lines[0]
    new_lines = [header]
    updated = False
    for line in lines[1:]:
        if line.startswith(f'"{title}"'):
            # Update the stats columns (Views,Likes,Comments)
            parts = line.split(",")
            parts[-3] = str(data.get("view_count", 0))
            parts[-2] = str(data.get("like_count", 0))
            parts[-1] = str(data.get("comment_count", 0))
            new_lines.append(",".join(parts))
            updated = True
        else:
            new_lines.append(line)
    if updated:
        csv_path.write_text("\n".join(new_lines), encoding="utf-8")
        print(f"♻ CSV stats updated for: {title}")

def update_txt(txt_path, data):
    """Update the TXT file with latest stats"""
    if not txt_path.exists():
        return
    content = txt_path.read_text(encoding="utf-8").splitlines()
    new_content = []
    for line in content:
        if line.startswith("  Views:"):
            new_content.append(f"  Views: {data.get('view_count', 0)}")
        elif line.startswith("  Likes:"):
            new_content.append(f"  Likes: {data.get('like_count', 0)}")
        elif line.startswith("  Comments:"):
            new_content.append(f"  Comments: {data.get('comment_count', 0)}")
        else:
            new_content.append(line)
    txt_path.write_text("\n".join(new_content), encoding="utf-8")
    print(f"♻ TXT stats updated: {txt_path}")

# ------------------ Download Function ------------------

def download_tiktok_profile(username, extra_options):
    base_dir = Path("TikTok Export") / username
    base_dir.mkdir(parents=True, exist_ok=True)

    profile_url = f"https://www.tiktok.com/@{username}"

    # Safe output template: folder max 50 chars, filename max 10 chars
    output_template = (
        "%(upload_date>%Y-%m-%d)s-"
        + username
        + " - %(title).50s/%(upload_date>%Y-%m-%d)s-"
        + username
        + " - %(title).10s.%(ext)s"
    )

    command = [
        "yt-dlp",
        profile_url,
        "-o", str(base_dir / output_template),
        "--merge-output-format", "mp4",
        "--write-info-json",
        "--continue",
        "--no-warnings"
    ] + extra_options

    subprocess.run(command, check=True)
    return base_dir

# ------------------ Post-Processing ------------------

def post_process_videos(export_dir, username):
    csv_path = export_dir / "tiktok_export.csv"
    existing_episodes = load_existing_csv(csv_path)

    for info_file in export_dir.rglob("*.json"):
        if not info_file.is_file() or info_file.name.endswith(".txt"):
            continue

        with open(info_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        full_title = data.get("title", "").strip()
        sanitized_title = sanitize(full_title)
        description = data.get("description", "").strip()
        hashtags = extract_hashtags(description)
        views = data.get("view_count", 0)
        likes = data.get("like_count", 0)
        comments = data.get("comment_count", 0)
        video_url = data.get("webpage_url", "(No URL)")

        upload_date_raw = data.get("upload_date", "")
        if not upload_date_raw:
            continue
        upload_date = datetime.strptime(upload_date_raw, "%Y%m%d").strftime("%Y-%m-%d")

        # Episode folder
        folder_name = f"{upload_date}-{username} - {sanitize(sanitized_title[:50])}"
        new_folder = export_dir / folder_name
        new_folder.mkdir(parents=True, exist_ok=True)

        # TXT path
        txt_filename = sanitize(f"{upload_date}-{username} - {sanitized_title[:FILENAME_LENGTH]}.txt")
        txt_path = new_folder / txt_filename

        # If episode already in CSV, skip moving/downloading, just update stats
        if full_title in existing_episodes:
            print(f"⏭ Episode already in CSV: {full_title}. Updating stats only.")
            update_txt(txt_path, data)
            update_csv_row(csv_path, full_title, data)
            continue

        # Move video & JSON into folder
        for file in info_file.parent.iterdir():
            if file.is_file() and file.suffix in [".mp4", ".json"]:
                dest_file = new_folder / file.name
                if not dest_file.exists():
                    shutil.move(str(file), dest_file)

        # Rename media files safely
        for file in new_folder.iterdir():
            if file.suffix in [".mp4", ".json"]:
                short_title = sanitize(sanitized_title[:FILENAME_LENGTH])
                new_name = f"{upload_date}-{username} - {short_title}{file.suffix}"
                file.rename(new_folder / new_name)

        # Create TXT inside folder
        txt_contents = [
            "Title:",
            full_title or "(No title)",
            "",
            "Description:",
            description or "(No description)",
            "",
            "Hashtags:",
            hashtags,
            "",
            "Stats:",
            f"  Views: {views}",
            f"  Likes: {likes}",
            f"  Comments: {comments}",
            "",
            "Video URL:",
            video_url
        ]
        try:
            txt_path.write_text("\n".join(txt_contents), encoding="utf-8")
            print(f"📝 TXT created: {txt_path}")
        except Exception as e:
            print(f"⚠ Could not write TXT file {txt_path}: {e}")

# ------------------ CSV Generation ------------------

def generate_csv(export_dir):
    csv_path = export_dir / "tiktok_export.csv"
    download_date = datetime.now().strftime("%Y-%m-%d")

    rows = ["Name,Release date,Download date,Description,Video URL,Views,Likes,Comments"]

    for folder in export_dir.iterdir():
        if not folder.is_dir():
            continue
        for json_file in folder.glob("*.json"):
            if json_file.name.endswith(".txt"):
                continue
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            title = data.get("title", "").replace('"', '""')
            upload_date = data.get("upload_date", "")
            description = data.get("description", "").replace('"', '""')
            video_url = data.get("webpage_url", "(No URL)")
            views = data.get("view_count", 0)
            likes = data.get("like_count", 0)
            comments = data.get("comment_count", 0)

            if upload_date:
                upload_date = datetime.strptime(upload_date, "%Y%m%d").strftime("%Y-%m-%d")

            rows.append(f'"{title}",{upload_date},{download_date},"{description}","{video_url}",{views},{likes},{comments}')

    csv_path.write_text("\n".join(rows), encoding="utf-8")
    print(f"📄 CSV created: {csv_path}")

# ------------------ Main ------------------

def main():
    check_python_version()
    if not is_yt_dlp_installed():
        install_yt_dlp()

    username = input("Enter TikTok username (without @): ").strip()
    if not username:
        sys.exit("❌ Username required.")

    extra_options = get_download_options()
    export_dir = download_tiktok_profile(username, extra_options)
    post_process_videos(export_dir, username)
    generate_csv(export_dir)

    print("✅ TikTok export complete.")

if __name__ == "__main__":
    main()
