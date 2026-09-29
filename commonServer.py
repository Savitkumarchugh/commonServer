from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import os
import uuid


load_dotenv()


# ============================================================
# APP CONFIG
# ============================================================

app = Flask(__name__)
CORS(app)

MONGODB_URI = os.getenv("MONGODB_URI")

DATABASE_NAME = "music_player"


if not MONGODB_URI:
    raise ValueError("MONGODB_URI is not set in .env")


# ============================================================
# AVAILABLE GENRES
# ============================================================
#
# IMPORTANT:
# These values map the API genre name to the MongoDB
# collection name.
#
# Example:
#
# "Punjabi" -> songs_punjabi
#
# ============================================================

GENRE_COLLECTIONS = {

    "Punjabi": "songs_punjabi",

    "Hindi": "songs_hindi",

    "English": "songs_english",

    "Haryanvi": "songs_haryanvi"

}


# ============================================================
# MONGODB
# ============================================================

client = MongoClient(

    MONGODB_URI,

    maxPoolSize=100,

    minPoolSize=5,

    serverSelectionTimeoutMS=5000,

    connectTimeoutMS=5000,

    socketTimeoutMS=10000

)


client.admin.command("ping")


db = client[DATABASE_NAME]


# ============================================================
# EXISTING COLLECTIONS
# ============================================================

playback_collection = db["playback_sessions"]

history_collection = db["play_history"]


print("MongoDB connected successfully.")


# ============================================================
# HELPER: GET GENRE COLLECTION
# ============================================================

def get_genre_collection(genre):

    if not genre:

        return None


    collection_name = GENRE_COLLECTIONS.get(
        genre
    )


    if not collection_name:

        return None


    return db[collection_name]


# ============================================================
# INDEXES
# ============================================================


# ------------------------------------------------------------
# CREATE INDEXES FOR ALL GENRE COLLECTIONS
# ------------------------------------------------------------

for genre, collection_name in GENRE_COLLECTIONS.items():

    collection = db[collection_name]


    # UUID must be unique inside each genre collection

    collection.create_index(

        [("uuid", 1)],

        unique=True

    )


    # YouTube video ID

    collection.create_index(

        [("youtube.videoId", 1)]

    )


    # Song search

    collection.create_index(

        [
            ("song", 1),
            ("album", 1),
            ("songName", 1)
        ]

    )


# ------------------------------------------------------------
# PLAYBACK
# ------------------------------------------------------------

playback_collection.create_index(

    [("clientId", 1)],

    unique=True

)


# ------------------------------------------------------------
# HISTORY
# ------------------------------------------------------------

history_collection.create_index(

    [
        ("clientId", 1),
        ("playedAt", DESCENDING)
    ]

)


# ------------------------------------------------------------
# ACTIVE USERS
# ------------------------------------------------------------

playback_collection.create_index(

    [("lastSeen", DESCENDING)]

)


# ============================================================
# HELPER: SERIALIZE SONG
# ============================================================

def serialize_song(song):

    if not song:

        return None


    return {

        "uuid": song.get("uuid"),

        "song": song.get("song"),

        "album": song.get("album"),

        "songName": song.get("songName"),

        "originalDateCreated":
            song.get("originalDateCreated"),

        "duration":
            song.get("duration"),

        "youtubeQuery":
            song.get("youtubeQuery"),

        "youtube":
            song.get("youtube", {})

    }


# ============================================================
# HELPER: GET RANDOM SONG
# ============================================================

def get_random_song(genre):

    songs_collection = get_genre_collection(
        genre
    )


    if songs_collection is None:

        return None


    cursor = songs_collection.aggregate(

        [
            {
                "$sample": {
                    "size": 1
                }
            }
        ],

        allowDiskUse=False

    )


    return next(
        cursor,
        None
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route(
    "/music",
    methods=["GET"]
)
def home():

    return jsonify({

        "message":
            "Music API is running",

        "database":
            DATABASE_NAME,

        "genres":
            list(
                GENRE_COLLECTIONS.keys()
            )

    })


# ============================================================
# GET AVAILABLE GENRES
#
# GET /api/genres
# ============================================================

@app.route(
    "/api/genres",
    methods=["GET"]
)
def get_genres():

    genres = []


    for genre, collection_name in GENRE_COLLECTIONS.items():

        collection = db[
            collection_name
        ]


        count = collection.count_documents({})


        genres.append({

            "genre":
                genre,

            "collection":
                collection_name,

            "songCount":
                count

        })


    return jsonify({

        "success":
            True,

        "genres":
            genres

    })


# ============================================================
# API 1
# PLAYER ACTION
#
# POST /api/player/action
#
# NEXT:
#
# {
#     "clientId": "abc123",
#     "action": "next",
#     "genre": "Punjabi"
# }
#
#
# PREVIOUS:
#
# {
#     "clientId": "abc123",
#     "action": "previous",
#     "genre": "Punjabi"
# }
# ============================================================

@app.route(
    "/api/player/action",
    methods=["POST"]
)
def player_action():

    data = request.get_json(
        silent=True
    ) or {}


    client_id = data.get(
        "clientId"
    )

    action = data.get(
        "action"
    )

    genre = data.get(
        "genre"
    )


    # --------------------------------------------------------
    # Validate client
    # --------------------------------------------------------

    if not client_id:

        return jsonify({

            "success":
                False,

            "message":
                "clientId is required"

        }), 400


    # --------------------------------------------------------
    # Validate action
    # --------------------------------------------------------

    if action not in [
        "next",
        "previous"
    ]:

        return jsonify({

            "success":
                False,

            "message":
                "action must be 'next' or 'previous'"

        }), 400


    # --------------------------------------------------------
    # Validate genre
    # --------------------------------------------------------

    if not genre:

        return jsonify({

            "success":
                False,

            "message":
                "genre is required"

        }), 400


    if genre not in GENRE_COLLECTIONS:

        return jsonify({

            "success":
                False,

            "message":
                "Invalid genre",

            "availableGenres":
                list(
                    GENRE_COLLECTIONS.keys()
                )

        }), 400


    now = datetime.now(
        timezone.utc
    )


    # ========================================================
    # NEXT
    # ========================================================

    if action == "next":

        song = get_random_song(
            genre
        )


        if not song:

            return jsonify({

                "success":
                    False,

                "message":
                    f"No songs available for {genre}"

            }), 404


        song_data = serialize_song(
            song
        )


        # ----------------------------------------------------
        # Update playback session
        #
        # Store genre so previous/history knows where
        # the song came from.
        # ----------------------------------------------------

        playback_collection.update_one(

            {
                "clientId":
                    client_id
            },

            {

                "$set": {

                    "clientId":
                        client_id,

                    "currentSongId":
                        song_data["uuid"],

                    "currentGenre":
                        genre,

                    "lastSeen":
                        now,

                    "updatedAt":
                        now

                },

                "$setOnInsert": {

                    "createdAt":
                        now

                }

            },

            upsert=True

        )


        # ----------------------------------------------------
        # Add history
        # ----------------------------------------------------

        history_collection.insert_one({

            "historyId":
                str(
                    uuid.uuid4()
                ),

            "clientId":
                client_id,

            "songId":
                song_data["uuid"],

            "genre":
                genre,

            "playedAt":
                now

        })


        return jsonify({

            "success":
                True,

            "action":
                "next",

            "clientId":
                client_id,

            "genre":
                genre,

            "song":
                song_data

        })


    # ========================================================
    # PREVIOUS
    # ========================================================

    playback = playback_collection.find_one(

        {
            "clientId":
                client_id
        },

        {
            "currentSongId":
                1,

            "currentGenre":
                1
        }

    )


    if not playback:

        return jsonify({

            "success":
                False,

            "message":
                "No playback session found"

        }), 404


    # --------------------------------------------------------
    # Get latest 2 history records
    # --------------------------------------------------------

    history = history_collection.find(

        {
            "clientId":
                client_id
        },

        {
            "songId":
                1,

            "genre":
                1,

            "playedAt":
                1
        }

    ).sort(

        "playedAt",

        DESCENDING

    ).limit(2)


    history = list(
        history
    )


    if len(history) < 2:

        return jsonify({

            "success":
                False,

            "message":
                "No previous song available"

        }), 404


    # --------------------------------------------------------
    # Previous song
    # --------------------------------------------------------

    previous_song_id = history[1][
        "songId"
    ]

    previous_genre = history[1].get(
        "genre"
    )


    if not previous_genre:

        previous_genre = genre


    # --------------------------------------------------------
    # Get correct genre collection
    # --------------------------------------------------------

    previous_collection = get_genre_collection(
        previous_genre
    )


    if previous_collection is None:

        return jsonify({

            "success":
                False,

            "message":
                "Invalid previous song genre"

        }), 400


    # --------------------------------------------------------
    # Get previous song
    # --------------------------------------------------------

    previous_song = previous_collection.find_one(

        {
            "uuid":
                previous_song_id
        }

    )


    if not previous_song:

        return jsonify({

            "success":
                False,

            "message":
                "Previous song no longer exists"

        }), 404


    previous_song_data = serialize_song(
        previous_song
    )


    # --------------------------------------------------------
    # Update playback session
    # --------------------------------------------------------

    playback_collection.update_one(

        {
            "clientId":
                client_id
        },

        {

            "$set": {

                "currentSongId":
                    previous_song_data["uuid"],

                "currentGenre":
                    previous_genre,

                "lastSeen":
                    now,

                "updatedAt":
                    now

            }

        }

    )


    return jsonify({

        "success":
            True,

        "action":
            "previous",

        "clientId":
            client_id,

        "genre":
            previous_genre,

        "song":
            previous_song_data

    })


# ============================================================
# API 2
# USER HISTORY
#
# GET /api/player/history/<client_id>
#
# Example:
#
# /api/player/history/abc123?limit=20
#
# Optional:
#
# /api/player/history/abc123?limit=20&genre=Punjabi
# ============================================================

@app.route(
    "/api/player/history/<client_id>",
    methods=["GET"]
)
def player_history(client_id):

    # --------------------------------------------------------
    # Limit
    # --------------------------------------------------------

    try:

        limit = int(

            request.args.get(
                "limit",
                20
            )

        )

    except ValueError:

        limit = 20


    limit = max(
        1,
        min(limit, 100)
    )


    # --------------------------------------------------------
    # Optional genre filter
    # --------------------------------------------------------

    genre = request.args.get(
        "genre"
    )


    if genre and genre not in GENRE_COLLECTIONS:

        return jsonify({

            "success":
                False,

            "message":
                "Invalid genre",

            "availableGenres":
                list(
                    GENRE_COLLECTIONS.keys()
                )

        }), 400


    # --------------------------------------------------------
    # Match
    # --------------------------------------------------------

    match_stage = {

        "clientId":
            client_id

    }


    if genre:

        match_stage["genre"] = genre


    # --------------------------------------------------------
    # Get history
    # --------------------------------------------------------

    history = list(

        history_collection.find(

            match_stage,

            {

                "_id":
                    0,

                "historyId":
                    1,

                "songId":
                    1,

                "genre":
                    1,

                "playedAt":
                    1

            }

        ).sort(

            "playedAt",

            DESCENDING

        ).limit(limit)

    )


    # --------------------------------------------------------
    # Fetch songs from their respective collections
    #
    # Because songs are stored in separate collections,
    # MongoDB $lookup cannot dynamically choose a collection.
    #
    # So we fetch them efficiently in grouped queries.
    # --------------------------------------------------------

    songs_by_genre = {}


    for history_item in history:

        item_genre = history_item.get(
            "genre"
        )


        if not item_genre:

            continue


        if item_genre not in songs_by_genre:

            songs_by_genre[
                item_genre
            ] = []


        songs_by_genre[
            item_genre
        ].append(

            history_item["songId"]

        )


    # --------------------------------------------------------
    # Fetch songs
    # --------------------------------------------------------

    song_map = {}


    for item_genre, song_ids in songs_by_genre.items():

        collection = get_genre_collection(
            item_genre
        )


        if collection is None:

            continue


        songs = collection.find({

            "uuid": {
                "$in":
                    song_ids
            }

        })


        for song in songs:

            song_map[

                (
                    item_genre,
                    song["uuid"]
                )

            ] = serialize_song(
                song
            )


    # --------------------------------------------------------
    # Build history response
    # --------------------------------------------------------

    response_history = []


    for history_item in history:

        item_genre = history_item.get(
            "genre"
        )


        song = song_map.get(

            (
                item_genre,
                history_item["songId"]
            )

        )


        if not song:

            continue


        response_history.append({

            "playedAt":
                history_item["playedAt"],

            "genre":
                item_genre,

            "song":
                song

        })


    return jsonify({

        "success":
            True,

        "clientId":
            client_id,

        "count":
            len(response_history),

        "history":
            response_history

    })


# ============================================================
# API 3
# ACTIVE USERS
#
# GET /api/stats/active-users
# ============================================================

@app.route(
    "/api/stats/active-users",
    methods=["GET"]
)
def active_users():

    now = datetime.now(
        timezone.utc
    )


    active_since = now - timedelta(
        minutes=5
    )


    active_count = playback_collection.count_documents({

        "lastSeen": {

            "$gte":
                active_since

        }

    })


    return jsonify({

        "success":
            True,

        "activeUsers":
            active_count,

        "activeWithinMinutes":
            5

    })


# ============================================================
# API 4
# ACTIVE USERS BY GENRE
#
# GET /api/stats/active-users?genre=Punjabi
# ============================================================

@app.route(
    "/api/stats/active-users/genre",
    methods=["GET"]
)
def active_users_by_genre():

    genre = request.args.get(
        "genre"
    )


    if genre not in GENRE_COLLECTIONS:

        return jsonify({

            "success":
                False,

            "message":
                "Invalid genre",

            "availableGenres":
                list(
                    GENRE_COLLECTIONS.keys()
                )

        }), 400


    now = datetime.now(
        timezone.utc
    )


    active_since = now - timedelta(
        minutes=5
    )


    active_count = playback_collection.count_documents({

        "lastSeen": {

            "$gte":
                active_since

        },

        "currentGenre":
            genre

    })


    return jsonify({

        "success":
            True,

        "genre":
            genre,

        "activeUsers":
            active_count,

        "activeWithinMinutes":
            5

    })


# ============================================================
# HEARTBEAT
#
# POST /api/player/heartbeat
#
# {
#     "clientId": "abc123",
#     "genre": "Punjabi"
# }
# ============================================================

@app.route(
    "/api/player/heartbeat",
    methods=["POST"]
)
def heartbeat():

    data = request.get_json(
        silent=True
    ) or {}


    client_id = data.get(
        "clientId"
    )


    genre = data.get(
        "genre"
    )


    if not client_id:

        return jsonify({

            "success":
                False,

            "message":
                "clientId is required"

        }), 400


    if genre and genre not in GENRE_COLLECTIONS:

        return jsonify({

            "success":
                False,

            "message":
                "Invalid genre",

            "availableGenres":
                list(
                    GENRE_COLLECTIONS.keys()
                )

        }), 400


    now = datetime.now(
        timezone.utc
    )


    update_data = {

        "lastSeen":
            now

    }


    if genre:

        update_data[
            "currentGenre"
        ] = genre


    playback_collection.update_one(

        {
            "clientId":
                client_id
        },

        {

            "$set":
                update_data,

            "$setOnInsert": {

                "clientId":
                    client_id,

                "createdAt":
                    now

            }

        },

        upsert=True

    )


    return jsonify({

        "success":
            True

    })


# ============================================================
# RUN APP
# ============================================================

if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        debug=True

    )