from discord.ext import commands
import discord

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from pydrive2.files import GoogleDriveFile

from pymongo import MongoClient
#dnspython==2.1.0

import requests
import re
from datetime import date
import zipfile as zp
import os
import io
import json
from PythonGists import Gist



#Init functions
def ourStrip(strIn):
    return "".join(c for c in strIn if c not in "_- .[]()")
def convertFileForPackage(inFile, fileName, zip):
    rawContents = inFile.read()

    if ".osu" in fileName:
        contentsList = rawContents.decode("utf-8").split("\r\n")
        contentsList = [line for line in contentsList if line != ""]

        for index, line in enumerate(contentsList):
            if "AudioFilename:" in line:
                contentsList[index] = f"AudioFilename: audio.mp3"
                break

        rawContents = "".join([string + "\r\n" for string in contentsList]).encode("utf-8")

        fileName = ourStrip(fileName.removesuffix(".osu")) + ".osu"

    elif ".mp3" in fileName or ".flac" in fileName or ".wav" in fileName or ".ogg" in fileName:
        fileName = "audio.mp3"

    else:
        return False

    zip.writestr(fileName, rawContents)



#Get the gist with all of our private keys
inDev = False
try:
    privateGist = Gist(os.environ["PRIVATE_GIST"]).getFileContent()
except:
    print("Unable to find config variables...")
    print("Loading from private...")

    try:
        with open("private.txt", "rt") as file:
            privateGist = Gist(file.readline()).getFileContent()
    except:
        print("Unable to find private...")
        quit()

    print("Running in dev because why not!")
    inDev = True

#Get private data (database connection, Discord token, etc.)
private = json.loads(privateGist["private.json"])

CONNECTION_STRING = private["db_connection"]
TOKEN = private["token"]


#Connect to the database
dbClient = MongoClient(CONNECTION_STRING)
DBINDEX = dbClient["UB-Database"]["Index"]


#Connect to google drive
UBMapsID = "1kmDCpmWQTIZRqhcvKsqzm4oZf2z6-mp5"

gauth = GoogleAuth()

#Load credentials
with open("mycreds.json", "w") as file:
    json.dump(json.loads(privateGist["mycreds.json"]), file)
gauth.ServiceAuth()
os.remove("mycreds.json")

if gauth.credentials is None:
    print("No credentials found...")
    quit()
elif gauth.access_token_expired:
    print("Token is expired...")
    quit()
else:
    print("Found the credentials!")

drive = GoogleDrive(gauth)


#Run the Discord bot
if not inDev:
    bot = commands.Bot(command_prefix="!")
else:
    bot = commands.Bot(command_prefix="?")



#Send message when online
@bot.event
async def on_ready():
    print(f"{bot.user} is online!")




#Functions to help uploading packages
def downloadFile(attachmentUrl):
    response = requests.get(attachmentUrl)
    fname = re.findall("filename=(.+)", response.headers['content-disposition'])[0]

    return (response, fname)
def getDataFromBmap(content):
    with zp.ZipFile(io.BytesIO(content), "r") as zip:
        title = ""
        artist = ""
        difficulties = {}

        for fileName in zip.namelist():
            with zip.open(fileName) as inFile:
                rawContents = inFile.read()

                if ".osu" in fileName:
                    contentsList = rawContents.decode("utf-8").split("\r\n")

                    for _, line in enumerate(contentsList):
                        if "Artist:" in line:
                            artist = line.replace("Artist:", "").strip()

                        elif "Version:" in line:
                            for _, line2 in enumerate(contentsList):
                                if "Creator:" in line2:
                                    difficulties[line.replace("Version:", "").strip()] = line2.replace("Creator:", "").strip()
                                    
                                    break

                        elif "Title:" in line:
                            title = line.replace("Title:", "").strip()

    return (title, artist, difficulties)

async def verifyPackage(title, artist, ctx):
    for _ in DBINDEX.find({"name": title, "artist": artist}):
        await ctx.send("That package does not pass our verifier...")
        return False
    return True
def sendToDatabase(content, fname, title, artist, difficulties):
    file = drive.CreateFile({"title": "ONLINE_" + fname, "parents": [{"id": UBMapsID}]})
    file.content = io.BytesIO(content)
    file.Upload()
    file.InsertPermission({"type": "anyone", "role": "reader"})

    DBINDEX.insert_one({ 

        "name": title,
        "date": date.today().strftime("%d/%m/%Y"),
        "file_id": file["id"],
        "artist": artist,
        "difficulties": difficulties

    })

    print("-------------------\n")
    print(fname)
    print(title)
    print(artist)
    print(difficulties)
    print("\nUploaded")
    print("\n-------------------\n")

async def uploadedMessage(fname, title, artist, difficulties, ctx):
    string = f"Uploaded the package: {fname}\nThis package includes the song {title} by {artist}\n\nVersions:"
    for dif in difficulties:
        string += f"\n{dif} mapped by {difficulties[dif]}"

    await ctx.send(string)


#Upload package commands
@bot.command(name="upload")
@commands.has_role("TacoDog")
async def uploadPackage(ctx):
    response, fname = downloadFile(ctx.message.attachments[0].url)

    if not zp.is_zipfile(io.BytesIO(response.content)) or os.path.splitext(fname) != ".bmap":
        await ctx.send("That is not a package")
        return

    title, artist, difficulties = getDataFromBmap(response.content)

    if await verifyPackage(title, artist, ctx):
        sendToDatabase(response.content, fname, title, artist, difficulties)
        await uploadedMessage(fname, title, artist, difficulties, ctx)

    response.close()

@bot.command(name="convertupload")
@commands.has_role("TacoDog")
async def convertUploadPackage(ctx):
    response, fname = downloadFile(ctx.message.attachments[0].url)
    fname = os.path.splitext(os.path.basename(fname))[0] + ".bmap"
    
    if not zp.is_zipfile(io.BytesIO(response.content)):
        await ctx.send("That is not a convertable file")
        return


    newZipIO = io.BytesIO()
    with zp.ZipFile(newZipIO, "w", compression=zp.ZIP_LZMA) as newZip:
        with zp.ZipFile(io.BytesIO(response.content), "r") as zip:
            for fileName in zip.namelist():
                with zip.open(fileName) as inFile:
                    convertFileForPackage(inFile, fileName, newZip)

    content = newZipIO.getvalue()
    title, artist, difficulties = getDataFromBmap(content)

    with zp.ZipFile(newZipIO, "a", compression=zp.ZIP_LZMA) as newZip:
        with newZip.open("info.json", "w") as infoFile:
            infoFile.write(json.dumps({
                                            "name": title, 
                                            "date": str(date.today().strftime("%d/%m/%Y")), 
                                            "artist": artist, 
                                            "difficulties": difficulties
                                        }, indent=4).encode("utf-8"))

    content = newZipIO.getvalue()
    title, artist, difficulties = getDataFromBmap(content)

    await ctx.send(f"Converted {title}")

    if await verifyPackage(title, artist, ctx):
        sendToDatabase(content, fname, title, artist, difficulties)
        await uploadedMessage(fname, title, artist, difficulties, ctx)

    response.close()


#Upload package error handling
@uploadPackage.error
@convertUploadPackage.error
async def info_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("You have the incorrect roles...")
        print(f"{ctx.author} had the wrong roles...")




#Show list of songs currently in the database
@bot.command(name="list")
async def listDatabase(ctx):
    string = "Song list:\n"
    for package in DBINDEX.find():
        ogString = string
        string += f"\n{package['name']} by {package['artist']}: https://drive.google.com/uc?export=download&id={package['file_id']}"

        if len(string) >= 2000:
            await ctx.send(ogString)
            string = ""
        
    await ctx.send(string)
    print("Sent the list!")




#Download packages
@bot.command(name="download")
async def downloadPackage(ctx, type, searchInput):
    print(f"Looking for {searchInput}...")
    await ctx.send(f'Sending all maps that I think are "{searchInput}"...')

    filesToSend = []

    for package in DBINDEX.aggregate([{"$search": {"text": {"query": searchInput, "path": "name"}}}]):
        response = requests.get(f"https://drive.google.com/uc?export=download&id={package['file_id']}")
        fname = re.findall("filename=\"(.+)\"", response.headers['content-disposition'])[0]

        print(f"Found {fname}!")

        if type == "bmap":
            filesToSend.append(discord.File(io.BytesIO(response.content), fname))
        elif type == "og":
            packageName = os.path.splitext(os.path.basename(fname))[0]          

            newZipIO = io.BytesIO()
            with zp.ZipFile(newZipIO, "w") as newZip:
                with zp.ZipFile(io.BytesIO(response.content), "r") as zip:
                    for fileName in zip.namelist():
                        with zip.open(fileName) as inFile:
                            rawContents = inFile.read()

                            if ".osu" in fileName:
                                contentsList = rawContents.decode("utf-8").split("\r\n")

                                for index, line in enumerate(contentsList):
                                    if "AudioFilename:" in line:
                                        contentsList[index] = f"AudioFilename: USER_BEATMAPS/{packageName}.mp3"
                                        break

                                rawContents = "".join([string + "\r\n" for string in contentsList]).encode("utf-8")

                            elif ".mp3" in fileName or ".flac" in fileName or ".wav" in fileName or ".ogg" in fileName:
                                fileName = f"{packageName}.mp3"

                            else:
                                continue

                            newZip.writestr(fileName, rawContents)
            
            filesToSend.append(discord.File(io.BytesIO(newZipIO.getvalue()), packageName + ".zip"))

        response.close()

    if filesToSend == []:
        await ctx.send("I couldn't find that package...")
        print(f"Couldn't find {searchInput}...")
    else:
        for file in filesToSend:
            await ctx.send(file=file)
        await ctx.send("Done!")
        print("Sent!")



@bot.command(name="delete")
@commands.has_role("Moderator")
async def delete(ctx, title):
    toLoop = DBINDEX.aggregate([{"$search": {"text": {"query": title, "path": "name"}}}])
    if title == "*":
        toLoop = DBINDEX.find()

    for package in toLoop:
        file = drive.CreateFile({"id": package["file_id"]})
        file.Delete()

        DBINDEX.delete_one(package)

        await ctx.send(f"Deleted {package['name']}!")
        print(f"Deleted {package['name']}!")

    await ctx.send("Done!")
    print("Done!")
        

@delete.error
async def info_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("HELL NAH")
        print(f"{ctx.author} had the wrong roles...")



@bot.command(name="ping")
async def ping(ctx):
    await ctx.send("pong")
    print("pong")

#Run the bot
bot.run(TOKEN)