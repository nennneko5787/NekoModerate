import discord
import discord.app_commands
import os
import asyncpg
import asyncio
from datetime import datetime
import re
import aiohttp

import random
import string

import traceback

from keep_alive import keep_alive

def generate_random_alphanumeric(length):
    alphanumeric = string.ascii_letters + string.digits
    return ''.join(random.choice(alphanumeric) for _ in range(length))

if os.path.isfile(".env") == True:
	from dotenv import load_dotenv
	load_dotenv(verbose=True)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

async def connect_to_db():
	return await asyncpg.connect(os.getenv("database"))

@client.event
async def on_ready():
	await tree.sync()
	print(f"Logged in {client.user}")

@client.event
async def on_guild_join(guild):
	for channel in guild.channels:
		if channel.permissions_for(guild.me).send_messages == True:
			embed = discord.Embed(
				title="NekoModerateを導入していただき、誠にありがとうございます。",
				description="当ボットを利用になる場合は、以下の操作を行ってください。\n`/logchannel` コマンドを使用し、ログを送信するチャンネルを選択する。\nこの操作を行わない場合、ログは確認できません。"
			)
			break

class Report(discord.ui.Modal):
	def __init__(self, member: discord.Member):
		super.__init__(title='ユーザーをグローバルBANシステムへ通報する')
		self.member = member
		self.reason = discord.ui.TextInput(
			label='グローバルBANシステムへ通報する理由',
			style=discord.TextStyle.long,
			placeholder=f'{member.display_name} を通報する理由を書いてください。',
			required=True,
			max_length=300,
		)

	async def on_submit(self, interaction: discord.Interaction):
		async with aiohttp.ClientSession() as session:
			webhook = discord.Webhook.from_url(os.getenv("webhook"), session=session)
			embed = discord.Embed(title="通報されました。", description=f"理由: {self.reason.value}", timestamp=datetime.now(), colour=discord.Colour.red())
			embed.add_field(name="ユーザー", value=f"{self.member.mention}(ID: `{self.member.name}`, Snowflake: `{self.member.id}`)")
			embed.add_field(name="通報したユーザー", value=f"{interaction.user.mention}(ID: `{interaction.user.name}`, Snowflake: `{interaction.user.id}`)")
			await webhook.send(embed=embed, username="NekoModerateユーザー通報システム", avatar_url=client.user.display_avatar)
		await interaction.response.send_message(f'通報しました。受理され次第、アクションが実行されます。', ephemeral=True)

	async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
		await interaction.response.send_message('エラーが発生しました。ごめんなさい。', ephemeral=True)

		# Make sure we know what the error actually is
		traceback.print_exception(type(error), error, error.__traceback__)

@tree.context_menu(name="グローバルBANシステムに通報")
async def report(interaction: discord.Interaction, member: discord.Member):
	await interaction.response.send_modal(Report(member))

@client.event
async def on_member_join(member: discord.Member):
	connection = await connect_to_db()
	try:
		# globalbanテーブルからIDが100の行を取得します。
		row = await connection.fetchrow("SELECT * FROM globalban WHERE id = $1", member.id)
		
		# 行が存在する場合の処理
		if row:
			if row.get("is_banned", False) == True:
				now = datetime.now()
				embed = discord.Embed(
					title="あなたはnekoModerateによりグローバルBANされています！",
					description=f"理由: {row.get('reason', '<None>')}",
					timestamp=now,
					colour=discord.Colour.red()
				).set_author(
					name=member.guild.name,
					icon_url=member.guild.icon
				).set_footer(
					text="nekoModerate",
					icon_url=client.user.display_avatar
				)
				if member.dm_channel is None:
					await member.create_dm()
				await member.dm_channel.send(embed=embed)

				log_channel_id = await connection.fetchval('SELECT log_channel FROM guilds WHERE id = $1', member.guild.id)
				log_channel = client.get_channel(log_channel_id)
				if log_channel is not None:
					embed = discord.Embed(title="メンバーがグローバルBANシステムにより、BANされました。", description=f"理由: {row.get('reason', '<None>')}", timestamp=now, colour=discord.Colour.red())
					embed.add_field(name="ユーザー", value=member.mention)
					await log_channel.send(embed=embed)

				await member.ban(delete_message_days=7, reason=f"nekoModerateによりBAN: {row.get('reason', '<None>')}")

	finally:
		# 接続をクローズします。
		await connection.close()

def is_discord_invite_link(link):
	return "discord.gg/" in link or "discord.com/invite/" in link

def extract_links(text):
	# 正規表現パターン
	url_pattern = r'https?://\S+'
	# 正規表現にマッチする全てのURLを抽出してリストに格納
	links = re.findall(url_pattern, text)
	links = [re.sub(r'\?.*$', '', link) for link in links]
	return links

@client.event
async def on_message(message):
	# メッセージがBot自身のものであれば無視
	if message.author == client.user:
		return
	
	if message.author.bot == True:
		return

	print(message.content)

	# サーバーの招待リンクを取得
	invites = await message.guild.invites()

	# メッセージに含まれるリンクを取得
	links = extract_links(message.content)
	print(links)

	# リンクがない場合は処理を終了
	if not links:
		print("li return")
		return

	connection = await connect_to_db()

	iskickinvite = await connection.fetchval('SELECT iskickinvite FROM guilds WHERE id = $1', message.guild.id)
	if iskickinvite != True:
		print("ki return")
		return
	
	if message.channel.topic is not None and "discord_invite_accept" in message.channel.topic:
		print("di return")
		return

	log_channel_id = await connection.fetchval('SELECT log_channel FROM guilds WHERE id = $1', message.guild.id)
	log_channel = client.get_channel(log_channel_id)

	await connection.close()

	# メッセージに含まれるリンクがサーバーの招待リンクでない場合、メッセージを削除
	for link in links:
		if is_discord_invite_link(link):
			if not any(invite.url in link for invite in invites):
				if log_channel is not None:
					embed = discord.Embed(title="メッセージが削除されました。", description="理由: 他鯖招待リンク送信許可チャンネル以外での他鯖の招待リンク送信", timestamp=datetime.now(), colour=discord.Colour.red())
					embed.add_field(name="ユーザー", value=message.author.mention)
					embed.add_field(name="メッセージ内容", value=f"```\n{message.content}\n```")
					await log_channel.send(embed=embed)
				await message.delete()
				break

@tree.command(name="globalban",description="グローバルBANシステムを有効化するかどうか。")
async def globalban(interaction: discord.Interaction, setting: bool):
	if interaction.user.guild_permissions.administrator:
		await interaction.response.defer()
		connection = await connect_to_db()
		await connection.execute('''
			INSERT INTO guilds (id, isglobalban) 
			VALUES ($1, $2) 
			ON CONFLICT (id) 
			DO UPDATE SET isglobalban = $2
		''', interaction.guild.id, setting)  # 例としてid=1のデータを挿入または更新する
		await connection.close()
		await interaction.followup.send(f"グローバルBANを有効化するかどうかを {setting} に設定しました。")
	else:
		await interaction.response.send_message("このコマンドを実行するためには、**管理者権限**が必要です！", ephemeral=True)

@tree.command(name="kickotherinvite",description="他鯖の招待リンクを消去するかどうか ※チャンネルごとに設定するにはチャンネルのトピックに「discord_invite_accept」を含めてください。")
async def kickotherinvite(interaction: discord.Interaction, setting: bool):
	if interaction.user.guild_permissions.administrator:
		await interaction.response.defer()
		connection = await connect_to_db()
		await connection.execute('''
			INSERT INTO guilds (id, iskickinvite) 
			VALUES ($1, $2) 
			ON CONFLICT (id) 
			DO UPDATE SET iskickinvite = $2
		''', interaction.guild.id, setting)  # 例としてid=1のデータを挿入または更新する
		await connection.close()
		await interaction.followup.send(f"招待リンクを消去するかどうかを {setting} に設定しました。")
	else:
		await interaction.response.send_message("このコマンドを実行するためには、**管理者権限**が必要です！", ephemeral=True)

@tree.command(name="logchannel",description="処理ログを送るチャンネルを変更することができます。")
async def logchannel(interaction: discord.Interaction, channel: discord.TextChannel):
	if interaction.user.guild_permissions.administrator:
		await interaction.response.defer()
		connection = await connect_to_db()
		await connection.execute('''
			INSERT INTO guilds (id, log_channel) 
			VALUES ($1, $2) 
			ON CONFLICT (id) 
			DO UPDATE SET log_channel = $2
		''', interaction.guild.id, channel.id)  # 例としてid=1のデータを挿入または更新する
		await connection.close()
		await interaction.followup.send(f"ログ通知先チャンネルを {channel.mention} に設定しました。")
	else:
		await interaction.response.send_message("このコマンドを実行するためには、**管理者権限**が必要です！", ephemeral=True)

keep_alive()
client.run(os.getenv("discord"))
