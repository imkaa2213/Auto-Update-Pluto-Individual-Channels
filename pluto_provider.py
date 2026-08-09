import json
import os
import re
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List

import requests


CHANNELS_FILE = "channels.json"


class PlutoProvider:
    def __init__(self, region="us"):
        self.region = region.lower()

        self.device_id = str(uuid.uuid4())
        self.session_token = None
        self.stitcher_params = ""
        self.session_expires_at = 0

        self.x_forward = {
            "us": "185.236.200.172",
            "gb": "84.17.50.173",
            "ca": "192.206.151.131",
            "fr": "176.31.84.249",
            "de": "217.94.184.66",
            "es": "88.26.241.248",
            "it": "131.114.130.239",
            "br": "177.192.255.38",
            "mx": "200.68.128.83",
            "ar": "168.226.232.228",
            "cl": "181.200.138.240",
            "no": "78.26.38.103",
            "se": "185.6.8.2",
            "dk": "192.36.27.7",
        }

        self.headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "origin": "https://pluto.tv",
            "referer": "https://pluto.tv/",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
        }

        if self.region in self.x_forward:
            self.headers["X-Forwarded-For"] = self.x_forward[self.region]

    def get_timeout(self):
        return 30

    def get_session_token(self):
        """
        Creates or reuses a Pluto TV session.
        """

        if (
            self.session_token
            and datetime.now().timestamp() < self.session_expires_at
        ):
            return self.session_token

        url = "https://boot.pluto.tv/v4/start"

        params = {
            "appName": "web",
            "appVersion": "8.1.0",
            "deviceVersion": "133.0.0",
            "deviceModel": "web",
            "deviceMake": "chrome",
            "deviceType": "web",
            "clientID": self.device_id,
            "clientModelNumber": "1.0.0",
            "serverSideAds": "false",
            "architecture": "x86_64",
            "buildVersion": "1.0.0",
            "drmCapabilities": "widevine:L3",
        }

        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=self.get_timeout(),
            )

            response.raise_for_status()

            data = response.json()

            self.session_token = data.get("sessionToken", "")
            self.stitcher_params = data.get("stitcherParams", "")

            self.session_expires_at = (
                datetime.now().timestamp() + (4 * 3600)
            )

            if not self.session_token:
                print(
                    f"[{self.region}] ERROR: "
                    "Pluto returned no session token."
                )
                return None

            return self.session_token

        except Exception as exc:
            print(
                f"[{self.region}] ERROR starting Pluto session: {exc}"
            )
            return None

    def get_categories(self, headers):
        """
        Gets Pluto channel categories for the selected region.
        """

        url = (
            "https://service-channels.clusters.pluto.tv/"
            "v2/guide/categories"
        )

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=self.get_timeout(),
            )

            response.raise_for_status()

            data = response.json().get("data", [])

            category_map = {}

            for category in data:
                category_name = category.get(
                    "name",
                    "Pluto TV",
                )

                for channel_id in category.get(
                    "channelIDs",
                    [],
                ):
                    category_map[
                        str(channel_id)
                    ] = category_name

            return category_map

        except Exception as exc:
            print(
                f"[{self.region}] WARNING: "
                f"Could not load categories: {exc}"
            )

            return {}

    def get_channels(self) -> List[Dict[str, Any]]:
        """
        Gets all Pluto channels available in the selected region.
        """

        token = self.get_session_token()

        if not token:
            return []

        url = (
            "https://service-channels.clusters.pluto.tv/"
            "v2/guide/channels"
        )

        headers = self.headers.copy()
        headers["authorization"] = f"Bearer {token}"

        try:
            response = requests.get(
                url,
                params={"limit": "1000"},
                headers=headers,
                timeout=self.get_timeout(),
            )

            response.raise_for_status()

            data = response.json().get("data", [])

            categories = self.get_categories(headers)

            channels = []

            for channel in data:
                channel_id = channel.get("id")
                name = channel.get("name")

                if not channel_id or not name:
                    continue

                channel_id = str(channel_id)

                logo = next(
                    (
                        image.get("url")
                        for image in channel.get(
                            "images",
                            [],
                        )
                        if image.get("type")
                        == "colorLogoPNG"
                    ),
                    "",
                )

                group = categories.get(
                    channel_id,
                    "Pluto TV",
                )

                quality_suffix = (
                    "&quality=720p"
                    "&deviceMake=chrome"
                    "&deviceType=web"
                    "&deviceModel=web"
                    "&deviceVersion=133.0.0"
                    "&architecture=x86_64"
                    "&buildVersion=1.0.0"
                    "&includeExtendedEvents=true"
                    "&masterJWTPassthrough=true"
                )

                stream_url = (
                    "https://"
                    "cfd-v4-service-channel-stitcher-use1-1"
                    ".prd.pluto.tv/v2/stitch/hls/channel/"
                    f"{channel_id}/master.m3u8?"
                    f"{self.stitcher_params}"
                    f"&jwt={token}"
                    f"{quality_suffix}"
                )

                channels.append(
                    {
                        "id": channel_id,
                        "name": name,
                        "logo": logo,
                        "group": group,
                        "stream_url": stream_url,
                    }
                )

            print(
                f"[{self.region}] "
                f"Found {len(channels)} Pluto channels."
            )

            return channels

        except Exception as exc:
            print(
                f"[{self.region}] ERROR loading channels: {exc}"
            )

            return []


def load_channel_config():
    """
    Loads channels.json from the repository root.
    """

    if not os.path.exists(CHANNELS_FILE):
        print(
            f"ERROR: {CHANNELS_FILE} was not found."
        )
        sys.exit(1)

    try:
        with open(
            CHANNELS_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            config = json.load(file)

    except json.JSONDecodeError as exc:
        print(
            f"ERROR: Invalid JSON in "
            f"{CHANNELS_FILE}: {exc}"
        )
        sys.exit(1)

    except Exception as exc:
        print(
            f"ERROR reading {CHANNELS_FILE}: {exc}"
        )
        sys.exit(1)

    if not isinstance(config, list):
        print(
            "ERROR: channels.json must "
            "contain a JSON array."
        )
        sys.exit(1)

    return config


def safe_filename(name):
    """
    Removes characters that cannot safely be
    used in filenames while preserving spaces.
    """

    name = re.sub(
        r'[<>:"/\\|?*]',
        "",
        name,
    )

    name = name.strip()

    return name


def make_m3u8_filename(item, configured_name):
    """
    Determines the output filename.

    If channels.json contains "filename", it will
    still normalize the extension to .m3u8.
    """

    filename = item.get("filename")

    if not filename:
        filename = safe_filename(
            configured_name
        )

    filename = filename.strip()

    # Remove an existing .m3u or .m3u8 extension.
    if filename.lower().endswith(".m3u8"):
        filename = filename[:-5]

    elif filename.lower().endswith(".m3u"):
        filename = filename[:-4]

    return filename + ".m3u8"


def make_playlist(
    channel,
    config,
    region,
):
    """
    Creates the contents of one individual
    extended M3U8 playlist.
    """

    channel_id = channel["id"]

    name = config.get(
        "name",
        channel["name"],
    )

    logo = config.get(
        "logo",
        channel["logo"],
    )

    group = config.get(
        "group",
        channel["group"],
    )

    epg = config.get(
        "epg",
        (
            "https://github.com/"
            "matthuisman/i.mjh.nz/"
            "raw/master/PlutoTV/"
            f"{region}.xml.gz"
        ),
    )

    return (
        f'#EXTM3U url-tvg="{epg}"\n'
        "#EXTINF:-1 "
        f'tvg-id="{channel_id}" '
        f'tvg-logo="{logo}" '
        f'group-title="{group}",'
        f"{name}\n"
        f'{channel["stream_url"]}\n'
    )


def update_channels():
    """
    Reads channels.json, groups channels by
    region, retrieves each Pluto region only once,
    and generates one .m3u8 per configured channel.
    """

    config = load_channel_config()

    if not config:
        print(
            "channels.json contains no channels."
        )
        return True

    regions = {}

    for item in config:
        channel_id = str(
            item.get("id", "")
        ).strip()

        region = str(
            item.get("region", "us")
        ).lower().strip()

        if not channel_id:
            print(
                "WARNING: Skipping entry "
                "without an ID."
            )
            continue

        if not region:
            region = "us"

        if region not in regions:
            regions[region] = []

        regions[region].append(item)

    updated = 0
    missing = 0
    errors = 0

    for (
        region,
        requested_channels,
    ) in regions.items():

        print("")
        print(
            f"===== Region: "
            f"{region.upper()} ====="
        )

        provider = PlutoProvider(
            region
        )

        available_channels = (
            provider.get_channels()
        )

        if not available_channels:
            print(
                f"[{region}] ERROR: "
                "No channels returned."
            )

            print(
                "Existing M3U8 files "
                "will remain untouched."
            )

            errors += len(
                requested_channels
            )

            continue

        channel_index = {
            channel["id"]: channel
            for channel in available_channels
        }

        for item in requested_channels:

            channel_id = str(
                item.get("id", "")
            ).strip()

            configured_name = str(
                item.get(
                    "name",
                    channel_id,
                )
            ).strip()

            channel = channel_index.get(
                channel_id
            )

            if not channel:
                print(
                    f"NOT FOUND: "
                    f"{configured_name} "
                    f"({channel_id}) "
                    f"[{region}]"
                )

                # Never overwrite or remove a
                # previously working file simply
                # because Pluto temporarily does
                # not return the channel.
                missing += 1

                continue

            filename = make_m3u8_filename(
                item,
                configured_name,
            )

            playlist = make_playlist(
                channel,
                item,
                region,
            )

            try:
                with open(
                    filename,
                    "w",
                    encoding="utf-8",
                ) as file:
                    file.write(
                        playlist
                    )

                print(
                    f"UPDATED: {filename}"
                )

                updated += 1

            except Exception as exc:
                print(
                    f"ERROR writing "
                    f"{filename}: {exc}"
                )

                errors += 1

    print("")
    print(
        "===== Finished ====="
    )

    print(
        f"Updated: {updated}"
    )

    print(
        f"Not found: {missing}"
    )

    print(
        f"Errors: {errors}"
    )

    return errors == 0


if __name__ == "__main__":

    success = update_channels()

    if not success:
        sys.exit(1)
