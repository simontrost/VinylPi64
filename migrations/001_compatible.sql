
        CREATE TABLE IF NOT EXISTS songs (
            song_key TEXT PRIMARY KEY,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            album TEXT,
            cover_url TEXT,
            genre TEXT,
            genre_source TEXT,
            shazam_track_id TEXT,
            shazam_artist_id TEXT,
            play_count INTEGER NOT NULL DEFAULT 0 CHECK (play_count >= 0),
            duration_ms INTEGER,
            duration_minutes REAL,
            duration_source TEXT,
            measured_listen_seconds REAL,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS artist_totals (
            artist TEXT PRIMARY KEY,
            play_count INTEGER NOT NULL DEFAULT 0 CHECK (play_count >= 0),
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS album_sessions (
            album TEXT PRIMARY KEY,
            session_count INTEGER NOT NULL DEFAULT 0 CHECK (session_count >= 0),
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS listening_totals (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_seconds REAL NOT NULL DEFAULT 0,
            recalculated_at INTEGER,
            recalculated_from_song_counts INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS pickup_usage_totals (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_seconds REAL NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS duration_cache (
            cache_key TEXT PRIMARY KEY,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            album TEXT,
            duration_ms INTEGER NOT NULL,
            duration_minutes REAL NOT NULL,
            source TEXT,
            fetched_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS tag_cache (
            cache_key TEXT PRIMARY KEY,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            fetched_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS album_covers (
            album TEXT PRIMARY KEY,
            artist TEXT,
            play_count INTEGER NOT NULL DEFAULT 0,
            mbid TEXT,
            cover_url TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS current_status (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            artist TEXT,
            title TEXT,
            cover_url TEXT,
            album TEXT,
            genre TEXT,
            bg_color TEXT,
            source TEXT,
            spotify_url TEXT,
            track_id TEXT,
            artist_id TEXT,
            duration_ms INTEGER,
            discogs_release_id INTEGER,
            discogs_position TEXT,
            discogs_side TEXT,
            discogs_track_index INTEGER,
            discogs_track_count INTEGER,
            discogs_side_track_number INTEGER,
            discogs_side_track_count INTEGER,
            discogs_match_source TEXT,
            discogs_confidence REAL,
            discogs_cover_url TEXT,
            discogs_year INTEGER,
            discogs_label TEXT,
            discogs_catalog_number TEXT,
            discogs_expected_next_title TEXT,
            discogs_expected_next_artist TEXT,
            discogs_expected_next_position TEXT,
            discogs_expected_next_side TEXT,
            side_flip_prompt_active INTEGER NOT NULL DEFAULT 0,
            side_flip_from_side TEXT,
            side_flip_to_side TEXT,
            side_flip_next_title TEXT,
            side_flip_next_position TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );


        CREATE TABLE IF NOT EXISTS source_status (
            source TEXT PRIMARY KEY,
            status_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS spotify_account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            refresh_token TEXT NOT NULL,
            account_id TEXT,
            spotify_user_id TEXT,
            display_name TEXT,
            external_url TEXT,
            connected_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS discogs_releases (
            release_id INTEGER PRIMARY KEY,
            instance_id INTEGER,
            folder_id INTEGER,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            year INTEGER,
            country TEXT,
            label TEXT,
            catalog_number TEXT,
            format_text TEXT,
            thumb_url TEXT,
            cover_url TEXT,
            date_added TEXT,
            details_loaded INTEGER NOT NULL DEFAULT 0,
            synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        -- Folder names are fetched separately from Discogs, not during a full
        -- collection sync. They stay in the active profile's own database.
        CREATE TABLE IF NOT EXISTS discogs_folders (
            folder_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            name TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS discogs_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id INTEGER NOT NULL REFERENCES discogs_releases(release_id) ON DELETE CASCADE,
            track_index INTEGER NOT NULL,
            position TEXT,
            side TEXT,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            duration_seconds INTEGER,
            normalized_title TEXT NOT NULL,
            normalized_artist TEXT NOT NULL,
            UNIQUE(release_id, track_index)
        );

        CREATE TABLE IF NOT EXISTS discogs_sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            username TEXT,
            status TEXT NOT NULL DEFAULT 'never',
            message TEXT,
            last_error TEXT,
            releases_count INTEGER NOT NULL DEFAULT 0,
            tracks_count INTEGER NOT NULL DEFAULT 0,
            failed_releases INTEGER NOT NULL DEFAULT 0,
            last_synced_at INTEGER,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        INSERT OR IGNORE INTO discogs_sync_state (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS legacy_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            imported_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
            raw_json TEXT NOT NULL,
            UNIQUE(source_sha256)
        );

        INSERT OR IGNORE INTO listening_totals (id, total_seconds)
        VALUES (1, 0);

        INSERT OR IGNORE INTO pickup_usage_totals (id, total_seconds)
        VALUES (1, 0);
        

            CREATE TABLE IF NOT EXISTS spotify_songs (
                track_id TEXT PRIMARY KEY,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                artist_id TEXT,
                album TEXT,
                cover_url TEXT,
                genre TEXT,
                duration_ms INTEGER,
                play_count INTEGER NOT NULL DEFAULT 0,
                listened_seconds REAL NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS spotify_artist_totals (
                artist TEXT PRIMARY KEY,
                play_count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS spotify_album_totals (
                album TEXT PRIMARY KEY,
                artist TEXT,
                cover_url TEXT,
                play_count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS spotify_listening_totals (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_seconds REAL NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            INSERT OR IGNORE INTO spotify_listening_totals (id, total_seconds)
            VALUES (1, 0);

            CREATE TABLE IF NOT EXISTS spotify_genre_attempts (
                track_id TEXT PRIMARY KEY,
                last_attempt_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_spotify_songs_play_count
                ON spotify_songs(play_count DESC);
            CREATE INDEX IF NOT EXISTS idx_spotify_songs_artist
                ON spotify_songs(artist);
            CREATE INDEX IF NOT EXISTS idx_spotify_songs_album
                ON spotify_songs(album);
            

    CREATE TABLE IF NOT EXISTS yearly_plays (
        source TEXT NOT NULL CHECK(source IN ('vinyl', 'spotify')),
        year INTEGER NOT NULL,
        song_key TEXT NOT NULL,
        artist TEXT NOT NULL,
        title TEXT NOT NULL,
        album TEXT,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (source, year, song_key)
    );
    CREATE TABLE IF NOT EXISTS yearly_albums (
        source TEXT NOT NULL CHECK(source IN ('vinyl', 'spotify')),
        year INTEGER NOT NULL,
        album TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (source, year, album)
    );
    CREATE TABLE IF NOT EXISTS yearly_usage (
        source TEXT NOT NULL CHECK(source IN ('vinyl', 'spotify')),
        year INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('listening', 'pickup')),
        seconds REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (source, year, kind)
    );
    CREATE TABLE IF NOT EXISTS playback_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        event_type TEXT NOT NULL,
        occurred_at INTEGER NOT NULL,
        song_key TEXT,
        artist TEXT,
        title TEXT,
        album TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_playback_events_year_time ON playback_events(source, occurred_at DESC);
    CREATE INDEX IF NOT EXISTS idx_yearly_plays_year ON yearly_plays(source, year, count DESC);
    