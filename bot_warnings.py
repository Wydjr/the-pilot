# bot_warnings.py

import os
import json
import base64
import requests
import discord
from discord import app_commands
from datetime import datetime
from typing import List, Optional, Literal, Tuple

from permissions import has_app_access


# ------------------- GitHub Config -------------------

GITHUB_REPO = os.getenv("GITHUB_REPO", "wydjr/the-pilot")
GITHUB_FILE_PATH = "warnings.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}"
} if GITHUB_TOKEN else {}


# ------------------- Default JSON structure -------------------

DEFAULT_DATA = {
    "warnings": {},
    "blocked_warners": [],
    "ffa_enabled": False,
    "last_reset": None,
    "extra_var": None
}


# ------------------- Helpers -------------------

def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {
            1: "st",
            2: "nd",
            3: "rd"
        }.get(n % 10, "th")

    return f"{n}{suffix}"


def _gh_url():
    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    )


def _chunk(items: List[str], size: int):
    return [
        items[i:i + size]
        for i in range(0, len(items), size)
    ]


def _page_label(i: int, per_page: int, total: int):
    start = i * per_page + 1
    end = min((i + 1) * per_page, total)

    return f"Page {i+1} ({start}–{end})"


async def reply(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    *,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    ephemeral: bool = False,
):

    kwargs = {}

    if content is not None:
        kwargs["content"] = content

    if embed is not None:
        kwargs["embed"] = embed

    if view is not None:
        kwargs["view"] = view

    kwargs["ephemeral"] = ephemeral


    if interaction.response.is_done():
        return await interaction.followup.send(**kwargs)

    return await interaction.response.send_message(**kwargs)



# ------------------- GitHub Load / Save -------------------

def load_data() -> Tuple[dict, Optional[str]]:

    try:
        r = requests.get(
            _gh_url(),
            headers=HEADERS,
            timeout=10
        )

        if r.status_code == 200:

            content = r.json()

            raw = base64.b64decode(
                content["content"]
            ).decode()

            data = (
                json.loads(raw)
                if raw.strip()
                else DEFAULT_DATA.copy()
            )


            data.setdefault("warnings", {})
            data.setdefault("blocked_warners", [])
            data.setdefault("ffa_enabled", False)
            data.setdefault("last_reset", None)
            data.setdefault("extra_var", None)


            return data, content.get("sha")


        if r.status_code == 404:

            sha = save_data(
                DEFAULT_DATA.copy(),
                sha=None
            )

            return DEFAULT_DATA.copy(), sha


        sha = save_data(
            DEFAULT_DATA.copy(),
            sha=None
        )

        return DEFAULT_DATA.copy(), sha


    except Exception:

        sha = save_data(
            DEFAULT_DATA.copy(),
            sha=None
        )

        return DEFAULT_DATA.copy(), sha



def save_data(
    data: dict,
    sha: Optional[str] = None
):

    payload = {
        "message": "Update warnings.json",
        "content": base64.b64encode(
            json.dumps(
                data,
                indent=4
            ).encode()
        ).decode()
    }


    if sha:
        payload["sha"] = sha


    try:

        r = requests.put(
            _gh_url(),
            headers=HEADERS,
            data=json.dumps(payload),
            timeout=10
        )


        if r.status_code in (200, 201):

            return (
                r.json()
                .get("content", {})
                .get("sha")
            )


        if r.status_code == 409:

            _, fresh_sha = load_data()

            payload["sha"] = fresh_sha


            r2 = requests.put(
                _gh_url(),
                headers=HEADERS,
                data=json.dumps(payload),
                timeout=10
            )


            if r2.status_code in (200, 201):

                return (
                    r2.json()
                    .get("content", {})
                    .get("sha")
                )


    except Exception:
        pass


    return sha

# ------------------- Warning Operations -------------------

def add_warning(user_id: int, reason: str | None = None) -> int:

    data, sha = load_data()

    uid = str(user_id)

    if uid not in data["warnings"]:
        data["warnings"][uid] = []

    data["warnings"][uid].append(
        reason or "No reason provided"
    )

    save_data(data, sha)

    return len(data["warnings"][uid])



def get_warnings(user_id: int) -> List[str]:

    data, _ = load_data()

    return data["warnings"].get(
        str(user_id),
        []
    )



def get_all_warnings() -> dict:

    data, _ = load_data()

    return data["warnings"]



# ------------------- Dropdown Pagination -------------------

class PageSelect(discord.ui.Select):

    def __init__(self, parent_view: "PagedEmbedView"):

        self.parent_view = parent_view

        options = []

        for i in range(len(parent_view.embeds)):

            options.append(
                discord.SelectOption(
                    label=_page_label(
                        i,
                        parent_view.per_page,
                        parent_view.total_items
                    ),
                    value=str(i)
                )
            )


        super().__init__(
            placeholder="Select a page…",
            min_values=1,
            max_values=1,
            options=options
        )


    async def callback(self, interaction: discord.Interaction):

        self.parent_view.index = int(
            self.values[0]
        )


        await interaction.response.edit_message(
            embed=self.parent_view.embeds[
                self.parent_view.index
            ],
            view=self.parent_view
        )



class PagedEmbedView(discord.ui.View):

    def __init__(
        self,
        embeds: List[discord.Embed],
        per_page: int,
        total_items: int
    ):

        super().__init__(
            timeout=180
        )

        self.embeds = embeds
        self.index = 0
        self.per_page = per_page
        self.total_items = total_items

        self.add_item(
            PageSelect(self)
        )



# ------------------- Embed Builders -------------------

def build_warnings_list_embeds(
    target: discord.Member,
    warns: List[str],
    per_page: int = 10
):

    lines = [
        f"**{i+1}.** {w}"
        for i, w in enumerate(warns)
    ]


    pages = (
        _chunk(lines, per_page)
        if lines
        else [[]]
    )


    embeds = []


    for i, chunk_lines in enumerate(pages):

        embed = discord.Embed(
            title=f"⚠️ Warnings for {target.display_name}"
        )


        embed.description = (
            "\n".join(chunk_lines)
            if chunk_lines
            else "No warnings."
        )


        embed.set_footer(
            text=f"Page {i+1}/{len(pages)}"
        )


        embeds.append(embed)


    return embeds



def build_server_warnings_embeds(
    interaction: discord.Interaction,
    per_page: int = 10
):

    all_warns = get_all_warnings()


    rows = []


    for uid, warns in all_warns.items():

        member = interaction.guild.get_member(
            int(uid)
        )


        if member:

            rows.append(
                (
                    member.display_name,
                    len(warns)
                )
            )


    rows.sort(
        key=lambda x: x[1],
        reverse=True
    )


    total_items = len(rows)


    lines = [
        f"**{i+1}.** {name} — **{count}**"
        for i, (name, count)
        in enumerate(rows)
    ]


    pages = (
        _chunk(lines, per_page)
        if lines
        else [[]]
    )


    embeds = []


    for i, chunk_lines in enumerate(pages):

        embed = discord.Embed(
            title="📋 Server Warnings"
        )


        embed.description = (
            "\n".join(chunk_lines)
            if chunk_lines
            else "No warnings found for this server."
        )


        embed.set_footer(
            text=f"Page {i+1}/{len(pages)}"
        )


        embeds.append(embed)


    return embeds, total_items

# ------------------- Command Setup -------------------

def setup_warnings_commands(tree: app_commands.CommandTree):


    # ---------------- /warningsmode ----------------

    @tree.command(
        name="warningsmode",
        description="Set how warnings work on this server."
    )
    @app_commands.describe(
        mode="restricted = role based, free_for_all = anyone can warn"
    )
    async def warningsmode(
        interaction: discord.Interaction,
        mode: Literal["restricted", "free_for_all"]
    ):

        if not has_app_access(
            interaction.user,
            "warnings"
        ):
            await reply(
                interaction,
                "❌ You do not have permission to change warning mode.",
                ephemeral=False
            )
            return


        data, sha = load_data()


        if mode == "free_for_all":

            data["ffa_enabled"] = True

            save_data(
                data,
                sha
            )

            await reply(
                interaction,
                "🔓 **Warnings free for all enabled**",
                ephemeral=False
            )


        else:

            data["ffa_enabled"] = False

            save_data(
                data,
                sha
            )

            await reply(
                interaction,
                "🔒 **Warning restrictions enabled**",
                ephemeral=False
            )



    # ---------------- /block_warner ----------------

    @tree.command(
        name="block_warner",
        description="Stop a user from warning people."
    )
    async def block_warner(
        interaction: discord.Interaction,
        member: discord.Member
    ):

        if not has_app_access(
            interaction.user,
            "warnings"
        ):
            await reply(
                interaction,
                "❌ You do not have permission.",
                ephemeral=False
            )
            return


        data, sha = load_data()

        data.setdefault(
            "blocked_warners",
            []
        )


        if member.id not in data["blocked_warners"]:

            data["blocked_warners"].append(
                member.id
            )

            save_data(
                data,
                sha
            )


        await reply(
            interaction,
            f"🚫 {member.mention} can no longer warn people.",
            ephemeral=False
        )



    # ---------------- /unblock_warner ----------------

    @tree.command(
        name="unblock_warner",
        description="Allow a user to warn again."
    )
    async def unblock_warner(
        interaction: discord.Interaction,
        member: discord.Member
    ):

        if not has_app_access(
            interaction.user,
            "warnings"
        ):
            await reply(
                interaction,
                "❌ You do not have permission.",
                ephemeral=False
            )
            return


        data, sha = load_data()


        if member.id in data.get(
            "blocked_warners",
            []
        ):

            data["blocked_warners"].remove(
                member.id
            )

            save_data(
                data,
                sha
            )


        await reply(
            interaction,
            f"✅ {member.mention} can warn again.",
            ephemeral=False
        )



    # ---------------- /warn ----------------

    @tree.command(
        name="warn",
        description="Warn a user."
    )
    @app_commands.describe(
        member="Member to warn",
        reason="Reason (optional)"
    )
    async def warn(
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = None
    ):

        author = interaction.user


        data, _ = load_data()


        # Blocked users

        if author.id in data.get(
            "blocked_warners",
            []
        ):

            await reply(
                interaction,
                f"❌ {author.mention} is blocked from warning people.",
                ephemeral=False
            )
            return



        # ONLY permission check

        if not has_app_access(
            author,
            "warnings"
        ):

            await reply(
                interaction,
                "❌ You do not have permission to warn people.",
                ephemeral=False
            )
            return



        # Normal warning

        count = add_warning(
            member.id,
            reason
        )


        msg = (
            f"⚠️ {member.mention} was warned"
        )


        if reason:

            msg += f" for {reason}"


        msg += (
            f", this is their {ordinal(count)} warning."
        )


        await reply(
            interaction,
            msg,
            ephemeral=False
        )



    # ---------------- /warnings_list ----------------

    @tree.command(
        name="warnings_list",
        description="List warnings."
    )
    @app_commands.describe(
        member="Member to view warnings for"
    )
    async def warnings_list(
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None
    ):

        target = (
            member
            or interaction.user
        )


        embeds = build_warnings_list_embeds(
            target,
            get_warnings(target.id),
            per_page=10
        )


        view = PagedEmbedView(
            embeds,
            10,
            len(get_warnings(target.id))
        )


        await reply(
            interaction,
            embed=embeds[0],
            view=view,
            ephemeral=False
        )



    # ---------------- /server_warnings ----------------

    @tree.command(
        name="server_warnings",
        description="Show server warnings."
    )
    async def server_warnings(
        interaction: discord.Interaction
    ):

        embeds, total = build_server_warnings_embeds(
            interaction,
            per_page=10
        )


        view = PagedEmbedView(
            embeds,
            10,
            total
        )


        await reply(
            interaction,
            embed=embeds[0],
            view=view,
            ephemeral=False
        )



    # ---------------- /clear_warnings ----------------

    @tree.command(
        name="clear_warnings",
        description="Clear warnings for a user."
    )
    async def clear_warnings(
        interaction: discord.Interaction,
        member: discord.Member
    ):

        if not has_app_access(
            interaction.user,
            "warnings"
        ):

            await reply(
                interaction,
                "❌ You do not have permission.",
                ephemeral=False
            )

            return


        data, sha = load_data()

        uid = str(member.id)


        if uid in data["warnings"]:

            data["warnings"].pop(uid)

            data["last_reset"] = (
                datetime.utcnow()
                .isoformat()
            )

            save_data(
                data,
                sha
            )


            await reply(
                interaction,
                f"✅ Cleared warnings for {member.mention}.",
                ephemeral=False
            )


        else:

            await reply(
                interaction,
                f"{member.mention} has no warnings.",
                ephemeral=False
            )



    # ---------------- /clear_server_warnings ----------------

    @tree.command(
        name="clear_server_warnings",
        description="Clear all server warnings."
    )
    async def clear_server_warnings(
        interaction: discord.Interaction
    ):

        if not has_app_access(
            interaction.user,
            "warnings"
        ):

            await reply(
                interaction,
                "❌ You do not have permission.",
                ephemeral=False
            )

            return


        data, sha = load_data()

        removed = len(
            data["warnings"]
        )


        data["warnings"] = {}

        data["last_reset"] = (
            datetime.utcnow()
            .isoformat()
        )


        save_data(
            data,
            sha
        )


        await reply(
            interaction,
            f"✅ Cleared {removed} warning records.",
            ephemeral=False
        )
