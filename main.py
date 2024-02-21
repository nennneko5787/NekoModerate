import discord
import discord.app_commands
import os
import asyncpg
import asyncio
from datetime import datetime
import re
from flask import Flask, render_template, request
from threading import Thread
import aiohttp

import random
import string

from werkzeug.routing import BaseConverter

from supabase import create_client, Client

import requests

class RegexConverter(BaseConverter):
  def __init__(self, url_map, *items):
    super(RegexConverter, self).__init__(url_map)
    self.regex = items[0]

def generate_random_alphanumeric(length):
    alphanumeric = string.ascii_letters + string.digits
    return ''.join(random.choice(alphanumeric) for _ in range(length))

if os.path.isfile(".env") == True:
	from dotenv import load_dotenv
	load_dotenv(verbose=True)

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

app = Flask('')
app.url_map.converters['regex'] = RegexConverter
app.config['TEMPLATES_AUTO_RELOAD'] = "isdev" in os.environ

async def connect_to_db():
	return await asyncpg.connect(user=os.getenv("db_user"), password=os.getenv("db_pass"),
								 database=os.getenv("db_name"), host=os.getenv("db_host"))

@client.event
async def on_ready():
	global connection
	connection = await connect_to_db()
	await tree.sync()
	print(f"Logged in {client.user}")

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

@tree.command(name="kickotherinvite",description="他鯖の招待リンクを消去するかどうか ※チャンネルごとに設定するにはチャンネルのトピックに「discord_invite_accept」を含めます。")
async def logchannel(interaction: discord.Interaction, setting: bool):
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

@tree.command(name="auth",description="設定変更")
async def logchannel(interaction: discord.Interaction, auth_role: discord.Role, ismanualauth: bool):
	if interaction.user.guild_permissions.administrator:
		await interaction.response.defer()
		await connection.execute('''
			INSERT INTO guilds (id, ismanualauth, auth_role) 
			VALUES ($1, $2, $3) 
			ON CONFLICT (id) 
			DO UPDATE SET ismanualauth = $2, auth_role = $3
		''', interaction.guild.id, ismanualauth, auth_role.id)  # 例としてid=1のデータを挿入または更新する
		await interaction.followup.send(f"```\n認証したあとにもらえるロール: {auth_role.name}\nメンバーを手動で認証するかどうか: {ismanualauth}```\n設定しました。")
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

@tree.command(name="auth_send",description="認証パネルを送信します")
async def logchannel(interaction: discord.Interaction):
	if interaction.user.guild_permissions.administrator:
		view = discord.ui.View()
		button = discord.ui.Button(label="認証",style=discord.ButtonStyle.success,custom_id=f"auth_siro,a")
		view.add_item(button)

		embed = discord.Embed(title="このサーバーに参加するためには、認証が必要です。", description="認証するには、下の「認証する」ボタンを押してください。", timestamp=datetime.now(), colour=discord.Colour.red())
		await interaction.channel.send(embed=embed,view=view)
		await interaction.response.send_message("送信しました。",ephemeral=True)
	else:
		await interaction.response.send_message("このコマンドを実行するためには、**管理者権限**が必要です！", ephemeral=True)

async def auth_role(guild, user):
	print(guild)
	auth_role = await connection.fetchval('SELECT auth_role FROM guilds WHERE id = $1', guild.id)
	role = guild.get_role(auth_role)
	await user.add_roles(role, "認証")

#全てのインタラクションを取得
@client.event
async def on_interaction(inter:discord.Interaction):
    try:
        if inter.data['component_type'] == 2:
            await on_button_click(inter)
        elif inter.data['component_type'] == 3:
            return
    except KeyError:
        pass

## Button,Selectの処理
async def on_button_click(interaction:discord.Interaction):
	name,value = interaction.data["custom_id"].split(",")
	if name == "auth":
		await interaction.response.send_message("")
		guild = await connection.fetchval('SELECT guild FROM auth WHERE id = $1', value)
		user = await connection.fetchval('SELECT user FROM auth WHERE id = $1', value)
		await connection.execute('''
			INSERT INTO guilds (id, authorized) 
			VALUES ($1, $2) 
			ON CONFLICT (id) 
			DO UPDATE SET authorized = $2
		''', value, True)  # 例としてid=1のデータを挿入または更新する
		server = client.get_guild(guild)
		member = server.get_member(user)
		embed = discord.Embed(title="メンバーが認証されました。", description="", timestamp=datetime.now(), colour=discord.Colour.green())
		embed.add_field(name="ユーザー", value=member.mention)
		embed.add_field(name="承認した人", value=interaction.user.mention)
		channel_id = await connection.fetchval('SELECT log_channel FROM guilds WHERE id = $1', server.id)
		channel = client.get_channel(channel_id)
		await channel.send_message(embed=embed)
	elif name == "auth_siro":
		code = generate_random_alphanumeric(10)
		print(interaction.guild.id)
		await connection.execute('''
			INSERT INTO auth (id, authorized, guild, "user") 
			VALUES ($1, $2, $3, $4) 
			ON CONFLICT (id) 
			DO UPDATE SET authorized = $2, guild = $3, "user" = $4
		''', code, False, interaction.guild.id, interaction.user.id)  # 例としてid=1のデータを挿入または更新する
		await interaction.response.send_message(f"以下のサイトから認証をお願いします。\nhttp://localhost:8080/auth/{code}", ephemeral=True)

@app.route('/')
async def home():
    return "Under maintenance"

@app.route("/auth/<regex(\"(.*)\"):code>")
async def authorize(code):
	return render_template('authorize.html', code=code)

@app.route("/authorize", methods=['POST'])
async def api_auth():
	code = request.form.get("code",None)
	turnstile = request.form.get("cf-turnstile-response",None)
		
	url = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
	payload = {'secret': os.getenv("turnstile"), 'response': turnstile, "remoteip": request.remote_addr}

	loop = asyncio.get_event_loop()

	response, c = await loop.run_in_executor(None,supabase.table('auth').select("*").eq("id",code).execute)
	print(response)
	guild = response[1][0]["guild"]
	gui, c = await loop.run_in_executor(None,supabase.table('guilds').select("*").eq("id",guild).execute)
	log_channel_id = gui[1][0]["log_channel"]
	log_channel = client.get_channel(log_channel_id)
	ismanualauth = gui[1][0]["ismanualauth"]
	user = response[1][0]["user"]

	server = client.get_guild(guild)
	member = server.get_member(user)

	response = requests.post(url, data=payload)
	if response.status_code == 200:
		data = response.json()
		if data["success"]:
			if not ismanualauth:
				auth_role(server, member)

				data, count = supabase.table('auth').upsert({'id': code, 'authorized': True}).execute()

				embed = discord.Embed(title="メンバーが認証されました。", description="", timestamp=datetime.now(), colour=discord.Colour.green())
				embed.add_field(name="ユーザー", value=member.mention)
				log_channel.send(embed=embed)
			else:
				view = discord.ui.View()
				button = discord.ui.Button(label="承認",style=discord.ButtonStyle.success,custom_id=f"auth,{code}")
				view.add_item(button)

				embed = discord.Embed(title="手動での認証が必要です。", description="承認するには、下の承認するボタンを教えて下さい。", timestamp=datetime.now(), colour=discord.Colour.red())
				embed.add_field(name="ユーザー", value=member.mention)
				log_channel.send(embed=embed,view=view)
		else:
			embed = discord.Embed(title="メンバーが認証されませんでした。", description="", timestamp=datetime.now(), colour=discord.Colour.green())
			embed.add_field(name="ユーザー", value=member.mention)
			log_channel.send(embed=embed)
			return "{\"success\": false}"

def run():
	app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()
client.run(os.getenv("discord"))