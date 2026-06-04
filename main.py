import os
import re
import asyncio
import time
from datetime import datetime, timedelta
from collections import defaultdict
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")

VIOLATION_KEYWORDS = {
    "hate_speech": [r"\b(example)\b"],
    "spam": [r"(https?://[^\s]+){3,}", r"(\S{25,})"],
    "harassment": [r"\b(kill yourself|kys|die|worthless)\b"],
    "nsfw": [r"\b(porn|xxx|nude)\b"],
}

SEVERITY = {"hate_speech": 10, "harassment": 8, "nsfw": 4, "spam": 3}

class WebhookManager:
    @staticmethod
    async def get_or_create_webhook(channel, name="load-tester"):
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.name == name:
                return wh
        return await channel.create_webhook(name=name)

    @staticmethod
    async def delete_webhook(webhook):
        try:
            await webhook.delete()
        except:
            pass

class BurstModal(discord.ui.Modal, title="Custom Burst"):
    count_input = discord.ui.TextInput(label="Messages", placeholder="1-5000", default="50")
    delay_input = discord.ui.TextInput(label="Delay (sec)", placeholder="0 = fastest", default="0")

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.count_input.value)
            delay = float(self.delay_input.value)
            if not (1 <= count <= 5000) or not (0 <= delay <= 10):
                raise ValueError
            self.view.custom_burst_count = count
            self.view.custom_burst_delay = delay
            await interaction.response.send_message(f"Custom burst: {count} msg, delay {delay}s", ephemeral=True)
        except:
            await interaction.response.send_message("Invalid numbers. Use 1-5000 for count, 0-10 for delay.", ephemeral=True)

class MessageModal(discord.ui.Modal, title="Set Webhook Message"):
    message_input = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, default="Load test payload")

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view.message_content = self.message_input.value
        await interaction.response.edit_message(content=f"Message updated:\n```{self.view.message_content}```", view=self.view)

class WebhookLoadTestView(discord.ui.View):
    def __init__(self, webhook, channel):
        super().__init__(timeout=600)
        self.webhook = webhook
        self.channel = channel
        self.message_content = "Load test payload"
        self.mention_everyone = False
        self.saved_bursts = 0
        self.custom_burst_count = 50
        self.custom_burst_delay = 0.0

    @property
    def content(self):
        msg = self.message_content
        if self.mention_everyone:
            msg = f"@everyone {msg}"
        return msg

    async def send_many(self, count, delay):
        async def send_one():
            try:
                await self.webhook.send(self.content)
                return True
            except:
                return False
        if delay == 0:
            tasks = [send_one() for _ in range(count)]
            results = await asyncio.gather(*tasks)
            return sum(results)
        else:
            ok = 0
            for _ in range(count):
                if await send_one():
                    ok += 1
                await asyncio.sleep(delay)
            return ok

    @discord.ui.button(label="SINGLE", style=discord.ButtonStyle.danger)
    async def single_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        ok = await self.send_many(1, 0)
        await interaction.followup.send("Sent 1 message." if ok else "Failed.", ephemeral=True)

    @discord.ui.button(label="BURST", style=discord.ButtonStyle.primary)
    async def burst_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        start = time.time()
        sent = await self.send_many(self.custom_burst_count, self.custom_burst_delay)
        elapsed = time.time() - start
        await interaction.followup.send(f"Sent {sent}/{self.custom_burst_count} messages in {elapsed:.2f}s.", ephemeral=True)

    @discord.ui.button(label="SAVE BURST", style=discord.ButtonStyle.success)
    async def save_burst(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.saved_bursts += 1
        total_saved = self.saved_bursts * 50
        await interaction.response.send_message(f"Saved burst #{self.saved_bursts} (50 messages). Total saved: {total_saved} messages.", ephemeral=True)

    @discord.ui.button(label="FIRE SAVED", style=discord.ButtonStyle.danger)
    async def fire_saved(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.saved_bursts == 0:
            await interaction.response.send_message("No saved bursts. Click SAVE BURST first.", ephemeral=True)
            return
        total_messages = self.saved_bursts * 50
        await interaction.response.defer(ephemeral=True)
        start = time.time()
        sent = await self.send_many(total_messages, delay=0.0)
        elapsed = time.time() - start
        self.saved_bursts = 0
        await interaction.followup.send(f"Fired {total_messages} messages. Sent: {sent}/{total_messages} in {elapsed:.2f}s.", ephemeral=True)

    @discord.ui.button(label="CUSTOM", style=discord.ButtonStyle.secondary)
    async def custom_burst(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BurstModal(self))

    @discord.ui.button(label="MESSAGE", style=discord.ButtonStyle.secondary)
    async def edit_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MessageModal(self))

    @discord.ui.button(label="MENTION", style=discord.ButtonStyle.secondary)
    async def toggle_mention(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mention_everyone = not self.mention_everyone
        button.label = f"MENTION {'ON' if self.mention_everyone else 'OFF'}"
        button.style = discord.ButtonStyle.success if self.mention_everyone else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="RESET", style=discord.ButtonStyle.danger)
    async def reset_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.message_content = "Load test payload"
        self.mention_everyone = False
        self.saved_bursts = 0
        self.custom_burst_count = 50
        self.custom_burst_delay = 0.0
        for child in self.children:
            if child.custom_id == self.toggle_mention.custom_id:
                child.label = "MENTION OFF"
                child.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(content="Reset to defaults.", view=self)

    async def on_timeout(self):
        await WebhookManager.delete_webhook(self.webhook)

def check_message(content: str):
    if not content:
        return []
    found = []
    for category, patterns in VIOLATION_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                found.append((category, pattern))
    return found

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.tree.sync()
    print("Slash commands synced")

@bot.hybrid_command(name="webhook_tester", description="Auto-create webhook & open flood panel")
async def webhook_tester(ctx: commands.Context):
    if not ctx.author.guild_permissions.manage_webhooks:
        await ctx.send("You need Manage Webhooks permission.", ephemeral=True)
        return
    webhook = await WebhookManager.get_or_create_webhook(ctx.channel, name="load-tester")
    view = WebhookLoadTestView(webhook, ctx.channel)
    embed = discord.Embed(title="Webhook Load Tester", description="Panel invisible to others. Use buttons to flood.")
    await ctx.send(embed=embed, view=view, ephemeral=True)

@bot.hybrid_command(name="scan_channel", description="Scan recent messages for policy violations (mod only)")
@commands.has_permissions(manage_messages=True)
async def scan_channel(ctx: commands.Context, limit: int = 100, hours: int = 24):
    await ctx.defer(ephemeral=True)
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    scanned = 0
    violations = defaultdict(list)
    total_score = 0

    async for message in ctx.channel.history(limit=min(limit, 1000)):
        if message.created_at.replace(tzinfo=None) < cutoff:
            break
        scanned += 1
        matches = check_message(message.content)
        for category, pattern in matches:
            violations[category].append({
                "link": message.jump_url,
                "author": str(message.author),
                "snippet": message.content[:100].replace('\n', ' '),
                "timestamp": message.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "pattern": pattern,
            })
            total_score += SEVERITY.get(category, 1)
        await asyncio.sleep(0.2)

    if not violations:
        embed = discord.Embed(title="Policy Scan Report", color=0x00ff00)
        embed.description = f"Scanned {scanned} messages from the last {hours} hours. No policy violations detected."
        await ctx.send(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(title="Policy Violation Scan Report", color=0xff0000, timestamp=datetime.utcnow())
    embed.set_footer(text=f"Scanned by {ctx.author}")
    embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
    embed.add_field(name="Messages Scanned", value=str(scanned), inline=True)
    embed.add_field(name="Total Severity Score", value=str(total_score), inline=True)

    for category, entries in list(violations.items())[:5]:
        value = f"{len(entries)} occurrence(s)\n"
        for e in entries[:3]:
            value += f"[{e['timestamp']}] {e['author']}: `{e['snippet']}` -> [{e['pattern']}]\n"
        if len(entries) > 3:
            value += f"... and {len(entries)-3} more.\n"
        embed.add_field(name=f"{category.upper()}", value=value[:1024], inline=False)

    report_url = "https://support.discord.com/hc/en-us/requests/new?ticket_form_id=360000029731"
    embed.add_field(name="Manual Reporting", value=f"To report to Discord:\n[Open Report Form]({report_url})\n\nCopy message links from above into the form.", inline=False)
    await ctx.send(embed=embed, ephemeral=True)

@bot.hybrid_command(name="scan_server", description="Scan all text channels for violations (mod only)")
@commands.has_permissions(manage_messages=True)
async def scan_server(ctx: commands.Context, limit_per_channel: int = 50, hours: int = 24):
    await ctx.defer(ephemeral=True)
    guild = ctx.guild
    total_scanned = 0
    total_violations = 0
    summary = []

    for channel in guild.text_channels:
        if not channel.permissions_for(guild.me).read_message_history:
            continue
        try:
            await ctx.send(f"Scanning #{channel.name}...", ephemeral=True)
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            channel_violations = 0
            async for msg in channel.history(limit=limit_per_channel):
                if msg.created_at.replace(tzinfo=None) < cutoff:
                    break
                total_scanned += 1
                if check_message(msg.content):
                    channel_violations += 1
                    total_violations += 1
                await asyncio.sleep(0.2)
            summary.append(f"#{channel.name}: {channel_violations} violations")
        except Exception as e:
            summary.append(f"#{channel.name}: error - {str(e)[:50]}")

    report_embed = discord.Embed(title="Server Policy Scan Summary", color=0xffaa00)
    report_embed.description = f"Scanned {total_scanned} messages across {len(summary)} channels. Total potential violations: {total_violations}"
    report_embed.add_field(name="Channel Breakdown", value="\n".join(summary[:20]), inline=False)
    report_embed.add_field(name="Next Steps", value="Use /scan_channel in specific channels for detailed evidence.\n[Discord Report Form](https://support.discord.com/hc/en-us/requests/new?ticket_form_id=360000029731)", inline=False)
    await ctx.send(embed=report_embed, ephemeral=True)

if __name__ == "__main__":
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Please set the DISCORD_TOKEN environment variable or edit the TOKEN variable in the script.")
    else:
        bot.run(TOKEN)