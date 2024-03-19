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
	global connection
	connection = await connect_to_db()
	await tree.sync()
	print(f"Logged in {client.user}")

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

	iskickinvite = await connection.fetchval('SELECT iskickinvite FROM guilds WHERE id = $1', message.guild.id)
	if iskickinvite != True:
		print("ki return")
		return
	
	if message.channel.topic is not None and "discord_invite_accept" in message.channel.topic:
		print("di return")
		return

	log_channel_id = await connection.fetchval('SELECT log_channel FROM guilds WHERE id = $1', message.guild.id)
	log_channel = client.get_channel(log_channel_id)

	# メッセージに含まれるリンクがサーバーの招待リンクでない場合、メッセージを削除
	for link in links:
		if is_discord_invite_link(link):
			if not any(invite.url in link for invite in invites):
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
		await connection.execute('''
			INSERT INTO guilds (id, isglobalban) 
			VALUES ($1, $2) 
			ON CONFLICT (id) 
			DO UPDATE SET isglobalban = $2
		''', interaction.guild.id, setting)  # 例としてid=1のデータを挿入または更新する
		await interaction.followup.send(f"グローバルBANを有効化するかどうかを {setting} に設定しました。")
	else:
		await interaction.response.send_message("このコマンドを実行するためには、**管理者権限**が必要です！", ephemeral=True)

@tree.command(name="kickotherinvite",description="他鯖の招待リンクを消去するかどうか ※チャンネルごとに設定するにはチャンネルのトピックに「discord_invite_accept」を含めてください。")
async def kickotherinvite(interaction: discord.Interaction, setting: bool):
	if interaction.user.guild_permissions.administrator:
		await interaction.response.defer()
		await connection.execute('''
			INSERT INTO guilds (id, iskickinvite) 
			VALUES ($1, $2) 
			ON CONFLICT (id) 
			DO UPDATE SET iskickinvite = $2
		''', interaction.guild.id, setting)  # 例としてid=1のデータを挿入または更新する
		await interaction.followup.send(f"招待リンクを消去するかどうかを {setting} に設定しました。")
	else:
		await interaction.response.send_message("このコマンドを実行するためには、**管理者権限**が必要です！", ephemeral=True)

@tree.command(name="logchannel",description="処理ログを送るチャンネルを変更することができます。")
async def logchannel(interaction: discord.Interaction, channel: discord.TextChannel):
	if interaction.user.guild_permissions.administrator:
		await interaction.response.defer()
		await connection.execute('''
			INSERT INTO guilds (id, log_channel) 
			VALUES ($1, $2) 
			ON CONFLICT (id) 
			DO UPDATE SET log_channel = $2
		''', interaction.guild.id, channel.id)  # 例としてid=1のデータを挿入または更新する
		await interaction.followup.send(f"ログ通知先チャンネルを {channel.mention} に設定しました。")
	else:
		await interaction.response.send_message("このコマンドを実行するためには、**管理者権限**が必要です！", ephemeral=True)

keep_alive()
client.run(os.getenv("discord"))
