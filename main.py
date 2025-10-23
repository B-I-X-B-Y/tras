import discord
from discord.ext import commands
from discord import app_commands
import requests
import json
import os
from dotenv import load_dotenv
import time # For ping command
import datetime # For banlist timestamp

# --- Configuration ---
load_dotenv() # Load variables from .env file if it exists

# --- Discord Config ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0")) 

# --- Roblox Config ---
ROBLOX_API_KEY = os.getenv("ROBLOX_API_KEY")       # Your Open Cloud API Key
ROBLOX_UNIVERSE_ID = os.getenv("ROBLOX_UNIVERSE_ID") # Your Roblox Universe ID
ROBLOX_MESSAGE_TOPIC = "TaurusAdminCommands"      # Must match Roblox script
ROBLOX_DATASTORE_NAME = os.getenv("ROBLOX_DATASTORE_NAME", "TaurusGlobalBans") # Must match Roblox Config.lua

# --- Security ---
INTERNAL_SECRET_KEY = os.getenv("INTERNAL_SECRET_KEY", "DEFAULT_CHANGE_THIS_SECRET") # Must match Roblox script
WHITELIST_FILE = "whitelist.json"

# --- Constants ---
EMBED_COLOR_SUCCESS = 0x00FF00
EMBED_COLOR_ERROR = 0xFF0000
EMBED_COLOR_INFO = 0x00BFFF
DATASTORE_API_URL = f"https://apis.roblox.com/datastores/v1/universes/{ROBLOX_UNIVERSE_ID}/standard-datastores"

# Basic check for essential config
if not all([DISCORD_BOT_TOKEN, BOT_OWNER_ID != 0, ROBLOX_API_KEY, ROBLOX_UNIVERSE_ID]):
    print("ERROR: Missing one or more configuration variables (Tokens, IDs). Check .env file.")
    exit()

# --- Whitelist Management ---
def load_whitelist():
    if not os.path.exists(WHITELIST_FILE): return []
    try:
        with open(WHITELIST_FILE, 'r') as f:
            content = f.read()
            if not content: return []
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError):
        print(f"Warning: Could not load or parse {WHITELIST_FILE}.")
        return []

def save_whitelist(whitelist_data):
    try:
        with open(WHITELIST_FILE, 'w') as f:
            json.dump(whitelist_data, f, indent=4)
    except IOError as e:
        print(f"Error saving whitelist: {e}")

# --- Bot Setup ---
intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
whitelisted_users = load_whitelist()

# --- Helper Functions ---
def is_whitelisted():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id == BOT_OWNER_ID or interaction.user.id in whitelisted_users:
            return True
        else:
            embed = discord.Embed(title="Access Denied", description="You are not authorized to use this command.", color=EMBED_COLOR_ERROR)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
    return app_commands.check(predicate)

def is_bot_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id == BOT_OWNER_ID:
            return True
        else:
            embed = discord.Embed(title="Access Denied", description="Only the bot owner can manage the whitelist.", color=EMBED_COLOR_ERROR)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
    return app_commands.check(predicate)

async def send_roblox_message(payload: dict):
    """Sends a message to Roblox via Open Cloud Messaging API."""
    url = f"https://apis.roblox.com/messaging-service/v1/universes/{ROBLOX_UNIVERSE_ID}/topics/{ROBLOX_MESSAGE_TOPIC}"
    headers = {"x-api-key": ROBLOX_API_KEY, "Content-Type": "application/json"}
    payload["internal_secret"] = INTERNAL_SECRET_KEY

    try:
        response = requests.post(url, headers=headers, data=json.dumps({"message": json.dumps(payload)}))
        response.raise_for_status()
        print(f"Sent message to Roblox: {payload}")
        return True, "Request sent to Roblox game servers."
    except requests.exceptions.RequestException as e:
        print(f"Error sending message to Roblox: {e}")
        error_message = f"Failed to send command to Roblox: {e}"
        if e.response is not None:
            try:
                error_details = e.response.json()
                error_message += f"\nDetails: {error_details.get('message', e.response.text)}"
            except json.JSONDecodeError:
                error_message += f"\nResponse: {e.response.text}"
        return False, error_message
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False, f"An unexpected error occurred: {e}"

async def get_username_from_id(user_id: int) -> str:
    """Fetches a Roblox username from a UserId using the Users API."""
    url = "https://users.roblox.com/v1/users"
    payload = {"userIds": [user_id], "excludeBannedUsers": False}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json().get('data', [])
        if data:
            return data[0].get('name', f"ID: {user_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching username for {user_id}: {e}")
    return f"ID: {user_id}"

def create_api_error_embed(error: requests.exceptions.RequestException, requested_perm: str) -> discord.Embed:
    """Creates a helpful embed when a 403 API error occurs."""
    if error.response is not None and error.response.status_code == 403:
        embed = discord.Embed(
            title="API Key Error (403 Forbidden)",
            description=f"The bot's API Key does not have the **`{requested_perm}`** permission for the DataStore API.",
            color=EMBED_COLOR_ERROR
        )
        embed.add_field(
            name="How to Fix",
            value=f"Go to your API Key settings on the Roblox Creator Dashboard and add the **`{requested_perm}`** operation to the **'DataStore'** API.",
            inline=False
        )
        try:
            error_details = error.response.json().get('message', error.response.text)
            embed.add_field(name="Raw Error", value=f"```\n{error_details}\n```", inline=False)
        except json.JSONDecodeError:
            embed.add_field(name="Raw Error", value=f"```\n{error.response.text}\n```", inline=False)
        return embed
    
    # Generic error
    embed = discord.Embed(title="API Request Failed", description=f"An error occurred while contacting the Roblox API.", color=EMBED_COLOR_ERROR)
    embed.add_field(name="Details", value=f"```\n{error}\n```")
    return embed

# --- Bot Events ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    print(f'Initial whitelist loaded: {whitelisted_users}')
    try:
        await bot.tree.sync()
        print("Synced global commands.")
    except Exception as e:
        print(f"Failed to sync global commands: {e}")

# --- Whitelist Management Commands ---
@bot.tree.command(name="whitelist", description="Manage the bot's authorized user list.")
@app_commands.describe(action="Add, remove, or list users.", user_id="Discord User ID to add/remove.")
@app_commands.choices(action=[
    app_commands.Choice(name="add", value="add"),
    app_commands.Choice(name="remove", value="remove"),
    app_commands.Choice(name="list", value="list"),
])
@is_bot_owner()
async def manage_whitelist(interaction: discord.Interaction, action: app_commands.Choice[str], user_id: str = None):
    global whitelisted_users
    action_value = action.value
    title = "Whitelist Management"
    description = "An error occurred."
    color = EMBED_COLOR_ERROR

    if action_value == "add":
        if not user_id or not user_id.isdigit():
            description = "Invalid or missing User ID for 'add' action."
        else:
            try:
                user_id_int = int(user_id)
                if user_id_int == BOT_OWNER_ID:
                     description = "The bot owner is always authorized."
                     color = EMBED_COLOR_INFO
                elif user_id_int not in whitelisted_users:
                    whitelisted_users.append(user_id_int)
                    save_whitelist(whitelisted_users)
                    description = f"User ID `{user_id_int}` added to the whitelist."
                    color = EMBED_COLOR_SUCCESS
                else:
                    description = f"User ID `{user_id_int}` is already in the whitelist."
                    color = EMBED_COLOR_INFO
            except ValueError:
                description = "Invalid User ID format."

    elif action_value == "remove":
        if not user_id or not user_id.isdigit():
            description = "Invalid or missing User ID for 'remove' action."
        else:
            try:
                user_id_int = int(user_id)
                if user_id_int in whitelisted_users:
                    whitelisted_users.remove(user_id_int)
                    save_whitelist(whitelisted_users)
                    description = f"User ID `{user_id_int}` removed from the whitelist."
                    color = EMBED_COLOR_SUCCESS
                else:
                    description = f"User ID `{user_id_int}` was not found in the whitelist."
                    color = EMBED_COLOR_INFO
            except ValueError:
                description = "Invalid User ID format."

    elif action_value == "list":
        if not whitelisted_users:
            description = "The whitelist is currently empty."
            color = EMBED_COLOR_INFO
        else:
            id_list = "\n".join([f"`{uid}`" for uid in whitelisted_users])
            title = "Whitelisted User IDs"
            description = id_list
            color = EMBED_COLOR_INFO

    embed = discord.Embed(title=title, description=description, color=color)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- Ping Command ---
@bot.tree.command(name="ping", description="Check the bot's latency.")
@is_whitelisted()
async def ping(interaction: discord.Interaction):
    start_time = time.time()
    await interaction.response.defer(ephemeral=True)
    end_time = time.time()
    
    bot_latency = bot.latency * 1000
    api_latency = (end_time - start_time) * 1000
    
    embed = discord.Embed(title="Pong! 🏓", color=EMBED_COLOR_INFO)
    embed.add_field(name="Bot Latency", value=f"{bot_latency:.2f} ms", inline=True)
    embed.add_field(name="API Latency", value=f"{api_latency:.2f} ms", inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)

# --- Game Server Commands (Messaging Service) ---
async def send_game_command_embed(interaction: discord.Interaction, command: str, target: str = None, arguments: str = None):
    """Helper for sending game server commands and replying with an embed."""
    await interaction.response.defer(ephemeral=True)
    payload = create_run_command_payload(interaction, command, target, arguments)
    success, message = await send_roblox_message(payload)
    
    if success:
        embed = discord.Embed(title=f"Command Sent: `:{command}`", description=message, color=EMBED_COLOR_SUCCESS)
    else:
        embed = discord.Embed(title=f"Command Failed: `:{command}`", description=message, color=EMBED_COLOR_ERROR)
        
    await interaction.followup.send(embed=embed, ephemeral=True)

def create_run_command_payload(interaction: discord.Interaction, command: str, target: str = None, arguments: str = None):
    return {"command_type": "RUN_COMMAND", "discord_user_id": str(interaction.user.id), "discord_user_name": interaction.user.display_name, "command": command, "target": target, "arguments": arguments }

@bot.tree.command(name="kick", description="Kick a player from the game.")
@app_commands.describe(player="Player name or @selector.", reason="Reason for kicking.")
@is_whitelisted()
async def kick_cmd(interaction: discord.Interaction, player: str, reason: str = None): 
    await send_game_command_embed(interaction, "kick", player, reason)

@bot.tree.command(name="announce", description="Send an announcement to all servers.")
@app_commands.describe(message="The announcement message.")
@is_whitelisted()
async def announce_cmd(interaction: discord.Interaction, message: str): 
    await send_game_command_embed(interaction, "announce", None, message)

@bot.tree.command(name="fly", description="Make a player fly.")
@app_commands.describe(player="Player name or @selector.")
@is_whitelisted()
async def fly_cmd(interaction: discord.Interaction, player: str): 
    await send_game_command_embed(interaction, "fly", player)

@bot.tree.command(name="unfly", description="Stop a player from flying.")
@app_commands.describe(player="Player name or @selector.")
@is_whitelisted()
async def unfly_cmd(interaction: discord.Interaction, player: str): 
    await send_game_command_embed(interaction, "unfly", player)

@bot.tree.command(name="serverlock", description="Lock all servers.")
@is_whitelisted()
async def serverlock_cmd(interaction: discord.Interaction): 
    await send_game_command_embed(interaction, "serverlock")

@bot.tree.command(name="unlock", description="Unlock all servers.")
@is_whitelisted()
async def unlock_cmd(interaction: discord.Interaction): 
    await send_game_command_embed(interaction, "unlock")

# --- DataStore API Commands (NEW) ---

@bot.tree.command(name="banid", description="Bans a player by UserId (offline) using DataStore.")
@app_commands.describe(user_id="Roblox UserId to ban.", reason="Reason for banning.")
@is_whitelisted()
async def banid_cmd(interaction: discord.Interaction, user_id: str, reason: str = "Banned via Discord."):
    await interaction.response.defer(ephemeral=True)
    if not user_id.isdigit():
        embed = discord.Embed(title="Invalid Input", description="UserId must be a number.", color=EMBED_COLOR_ERROR)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    user_id_int = int(user_id)
    username = await get_username_from_id(user_id_int)
    
    # Data to save to DataStore
    ban_data = {
        "Reason": reason,
        "BannedBy": f"{interaction.user.display_name} (Discord)",
        "Username": username,
        "Timestamp": int(time.time())
    }
    
    headers = {"x-api-key": ROBLOX_API_KEY, "Content-Type": "application/json"}
    # The API URL for setting an entry.
    url = f"{DATASTORE_API_URL}/datastore/entries/entry?datastoreName={ROBLOX_DATASTORE_NAME}&entryKey={user_id}"
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(ban_data))
        response.raise_for_status()
        
        embed = discord.Embed(title="User Banned (DataStore)", description=f"Successfully banned **{username}** (`{user_id}`).", color=EMBED_COLOR_SUCCESS)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Banned by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    except requests.exceptions.RequestException as e:
        embed = create_api_error_embed(e, "Write")
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="ban", description="Bans a player currently in the game. (Uses DataStore).")
@app_commands.describe(player="Player name. Must be exact.", reason="Reason for banning.")
@is_whitelisted()
async def ban_cmd(interaction: discord.Interaction, player: str, reason: str = "Banned via Discord."):
    await interaction.response.defer(ephemeral=True)

    # 1. Get UserId from Username
    user_id = None
    try:
        lookup_url = "https://users.roblox.com/v1/usernames/users"
        lookup_payload = {"usernames": [player], "excludeBannedUsers": False}
        response = requests.post(lookup_url, json=lookup_payload)
        response.raise_for_status()
        data = response.json().get('data', [])
        if data:
            user_id = data[0].get('id')
            username = data[0].get('name')
        else:
            embed = discord.Embed(title="User Not Found", description=f"Could not find a Roblox user named `{player}`.", color=EMBED_COLOR_ERROR)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
    except Exception as e:
        embed = discord.Embed(title="Username Lookup Failed", description=f"An error occurred trying to find `{player}`.\n```{e}```", color=EMBED_COLOR_ERROR)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # 2. Ban the UserId
    ban_data = {
        "Reason": reason,
        "BannedBy": f"{interaction.user.display_name} (Discord)",
        "Username": username,
        "Timestamp": int(time.time())
    }
    
    headers = {"x-api-key": ROBLOX_API_KEY, "Content-Type": "application/json"}
    url = f"{DATASTORE_API_URL}/datastore/entries/entry?datastoreName={ROBLOX_DATASTORE_NAME}&entryKey={user_id}"
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(ban_data))
        response.raise_for_status()
        
        embed = discord.Embed(title="User Banned (DataStore)", description=f"Successfully banned **{username}** (`{user_id}`).", color=EMBED_COLOR_SUCCESS)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Banned by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    except requests.exceptions.RequestException as e:
        embed = create_api_error_embed(e, "Write")
        await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="unban", description="Unban a player by UserId (removes DataStore ban).")
@app_commands.describe(user_id="Roblox UserId to unban.")
@is_whitelisted()
async def unban_cmd(interaction: discord.Interaction, user_id: str):
    await interaction.response.defer(ephemeral=True)
    if not user_id.isdigit():
        embed = discord.Embed(title="Invalid Input", description="UserId must be a number.", color=EMBED_COLOR_ERROR)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    headers = {"x-api-key": ROBLOX_API_KEY}
    url = f"{DATASTORE_API_URL}/datastore/entries/entry?datastoreName={ROBLOX_DATASTORE_NAME}&entryKey={user_id}"

    try:
        response = requests.delete(url, headers=headers)
        
        # 404 means the user wasn't banned anyway, which is a success
        if response.status_code == 404:
            embed = discord.Embed(title="User Unbanned", description=f"User `{user_id}` was not found in the ban list.", color=EMBED_COLOR_INFO)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        response.raise_for_status() # Raise error for other codes (like 403, 500)
        
        username = await get_username_from_id(int(user_id))
        embed = discord.Embed(title="User Unbanned (DataStore)", description=f"Successfully unbanned **{username}** (`{user_id}`).", color=EMBED_COLOR_SUCCESS)
        embed.set_footer(text=f"Unbanned by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    except requests.exceptions.RequestException as e:
        embed = create_api_error_embed(e, "Delete")
        await interaction.followup.send(embed=embed, ephemeral=True)

# --- Info Request Commands ---
async def get_datastore_ban_list():
    """Fetches and formats the ban list directly from the Open Cloud DataStore API."""
    print("Fetching ban list from DataStore API...")
    headers = {"x-api-key": ROBLOX_API_KEY}
    ban_keys = []
    next_cursor = ""
    
    # 1. List all keys
    try:
        while True:
            cursor_param = f"&cursor={next_cursor}" if next_cursor else ""
            list_url = f"{DATASTORE_API_URL}/datastore/entries?datastoreName={ROBLOX_DATASTORE_NAME}{cursor_param}"
            response = requests.get(list_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            ban_keys.extend([key['key'] for key in data.get('keys', [])])
            next_cursor = data.get('nextPageCursor')
            if not next_cursor:
                break
        print(f"Found {len(ban_keys)} ban keys.")
    except requests.exceptions.RequestException as e:
        print(f"Error listing DataStore keys: {e}")
        return False, e # Pass the exception object

    if not ban_keys:
        return True, []

    # 2. Get data for each key
    ban_list_strings = []
    for user_id_str in ban_keys:
        try:
            get_url = f"{DATASTORE_API_URL}/datastore/entries/entry?datastoreName={ROBLOX_DATASTORE_NAME}&entryKey={user_id_str}"
            response = requests.get(get_url, headers=headers)
            if response.status_code == 404: # Key listed but data gone?
                ban_list_strings.append(f"[ERROR] Data for key `{user_id_str}` was not found (404).")
                continue
            response.raise_for_status()
            
            ban_data = response.json()
            username = ban_data.get("Username", f"ID: {user_id_str}")
            banned_by = ban_data.get("BannedBy", "Unknown")
            reason = ban_data.get("Reason", "No reason") # Get reason
            timestamp = ban_data.get("Timestamp")
            
            date_str = "???"
            if timestamp:
                try: date_str = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
                except Exception: pass
            
            # Add reason to the string
            ban_list_strings.append(f"[{date_str}] **{username}** (By: {banned_by}) - *{reason}*")
            
        except requests.exceptions.RequestException as e:
            if e.response is not None and e.response.status_code == 403:
                return False, e # Fail fast on 403
            print(f"Error fetching data for key {user_id_str}: {e}")
            ban_list_strings.append(f"[ERROR] Could not fetch data for key: `{user_id_str}`")
        except json.JSONDecodeError:
            print(f"Error decoding JSON for key {user_id_str}")
            ban_list_strings.append(f"[ERROR] Corrupted data for key: `{user_id_str}`")

    ban_list_strings.sort()
    return True, ban_list_strings

@bot.tree.command(name="banlist", description="Request the global DataStore ban list.")
@is_whitelisted()
async def banlist_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    success, data = await get_datastore_ban_list()
    
    if not success:
        # data is an exception object here
        if isinstance(data, requests.exceptions.RequestException) and data.response is not None and data.response.status_code == 403:
            try:
                error_json = data.response.json()
                if "INSUFFICIENT_SCOPE" in error_json.get("message", ""):
                    if "ListEntries" in error_json.get("message", ""):
                        embed = create_api_error_embed(data, "List Keys")
                    else:
                        embed = create_api_error_embed(data, "Read")
                else:
                    embed = create_api_error_embed(data, "Read / List Keys")
            except json.JSONDecodeError:
                 embed = create_api_error_embed(data, "Read / List Keys")
        else:
            embed = discord.Embed(title="Error", description=f"Failed to retrieve ban list: \n```{data}```", color=EMBED_COLOR_ERROR)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
        
    embed = discord.Embed(
        title="Taurus Global Ban List",
        color=EMBED_COLOR_INFO,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    
    if not data:
        embed.description = "The DataStore ban list is empty."
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    embed.description = f"Found {len(data)} total entries."
    
    current_field_value = ""
    part = 1
    for entry in data:
        if len(current_field_value) + len(entry) + 2 > 1024:
            embed.add_field(name=f"Ban List (Part {part})", value=current_field_value, inline=False)
            current_field_value = entry + "\n"
            part += 1
        else:
            current_field_value += entry + "\n"
            
    if current_field_value:
        embed.add_field(name=f"Ban List (Part {part})", value=current_field_value, inline=False)

    if len(embed.fields) > 25:
        embed.clear_fields()
        embed.add_field(name="Error", value="Ban list is too large to display in a single embed.", inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="players", description="Request all servers to log their current player list.")
@is_whitelisted()
async def players_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    payload = {"command_type": "GET_PLAYER_LIST", "discord_user_id": str(interaction.user.id), "discord_user_name": interaction.user.display_name, }
    success, message = await send_roblox_message(payload)
    if success:
        embed = discord.Embed(title="Player List Requested", description="Request sent. Results will be logged to your 'BotLogs' webhook channel.", color=EMBED_COLOR_SUCCESS)
    else:
        embed = discord.Embed(title="Command Failed", description=message, color=EMBED_COLOR_ERROR)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="serveruptime", description="Request all servers to log their uptime.")
@is_whitelisted()
async def serveruptime_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    payload = {"command_type": "GET_SERVER_UPTIME", "discord_user_id": str(interaction.user.id), "discord_user_name": interaction.user.display_name, }
    success, message = await send_roblox_message(payload)
    if success:
        embed = discord.Embed(title="Server Uptime Requested", description="Request sent. Results will be logged to your 'BotLogs' webhook channel.", color=EMBED_COLOR_SUCCESS)
    else:
        embed = discord.Embed(title="Command Failed", description=message, color=EMBED_COLOR_ERROR)
    await interaction.followup.send(embed=embed, ephemeral=True)


# --- Start Bot ---
if __name__ == "__main__":
    if DISCORD_BOT_TOKEN:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        print("Bot token not found. Please set the DISCORD_BOT_TOKEN environment variable or in .env file.")