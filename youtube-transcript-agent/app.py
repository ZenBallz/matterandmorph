import re
from flask import Flask, jsonify, request
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import os

app = Flask(__name__)
CORS(app)

# You'll add your YouTube API key here
YOUTUBE_API_KEY = 'AIzaSyCeLeXjfx2BtN8fGBRTiYQXFaH4W6DaE2s'

@app.route('/api/discover-channel', methods=['POST'])
def discover_channel():
    """Discover all videos from a YouTube channel OR playlist"""
    try:
        data = request.json
        url = data.get('channel_url', '')
        
        # Build YouTube API client
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        
        # Check if it's a playlist URL
        playlist_match = re.search(r'list=([\w-]+)', url)
        
        if playlist_match:
            # It's a playlist!
            playlist_id = playlist_match.group(1)
            print(f"Detected playlist: {playlist_id}")
            
            # Get playlist info
            playlist_response = youtube.playlists().list(
                part='snippet',
                id=playlist_id
            ).execute()
            
            if not playlist_response['items']:
                return jsonify({'error': 'Playlist not found'}), 404
            
            playlist_info = playlist_response['items'][0]
            playlist_title = playlist_info['snippet']['title']
            
            # Get all video IDs from playlist
            video_ids = []
            next_page_token = None
            
            while True:
                playlist_items = youtube.playlistItems().list(
                    part='contentDetails',
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=next_page_token
                ).execute()
                
                for item in playlist_items['items']:
                    video_ids.append(item['contentDetails']['videoId'])
                
                next_page_token = playlist_items.get('nextPageToken')
                if not next_page_token:
                    break
            
            return jsonify({
                'channel_id': playlist_id,
                'channel_title': f'Playlist: {playlist_title}',
                'video_count': len(video_ids),
                'video_ids': video_ids
            })
        
        else:
            # It's a channel - use existing logic
            channel_id = extract_channel_id(url)
            
            if not channel_id:
                return jsonify({'error': 'Invalid channel or playlist URL'}), 400
            
            # Get channel info
            channel_response = youtube.channels().list(
                part='snippet,contentDetails,statistics',
                id=channel_id
            ).execute()
            
            if not channel_response['items']:
                return jsonify({'error': 'Channel not found'}), 404
            
            channel_info = channel_response['items'][0]
            uploads_playlist_id = channel_info['contentDetails']['relatedPlaylists']['uploads']
            
            # Get all video IDs from uploads playlist
            video_ids = []
            next_page_token = None
            
            while True:
                playlist_response = youtube.playlistItems().list(
                    part='contentDetails',
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=next_page_token
                ).execute()
                
                for item in playlist_response['items']:
                    video_ids.append(item['contentDetails']['videoId'])
                
                next_page_token = playlist_response.get('nextPageToken')
                if not next_page_token:
                    break
            
            return jsonify({
                'channel_id': channel_id,
                'channel_title': channel_info['snippet']['title'],
                'video_count': len(video_ids),
                'video_ids': video_ids
            })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/fetch-transcripts', methods=['POST'])
def fetch_transcripts():
    """Fetch transcripts for a list of video IDs"""
    try:
        data = request.json
        video_ids = data.get('video_ids', [])
        
        if not video_ids:
            return jsonify({'error': 'No video IDs provided'}), 400
        
        # Build YouTube API client for video details
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        
        transcripts = []
        failed = []
        
        # Process videos in batches of 50 (API limit)
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            
            # Get video details
            videos_response = youtube.videos().list(
                part='snippet',
                id=','.join(batch)
            ).execute()
            
            video_details = {item['id']: item['snippet'] for item in videos_response['items']}
            
            # Fetch transcripts
            for video_id in batch:
                try:
                    # Get transcript - CORRECTED to use new API
                    from youtube_transcript_api import YouTubeTranscriptApi
                    api = YouTubeTranscriptApi()
                    fetched_transcript = api.fetch(video_id)
                    transcript_text = ' '.join([snippet.text for snippet in fetched_transcript.snippets])
                    
                    # Get video details
                    details = video_details.get(video_id, {})
                    
                    transcripts.append({
                        'id': video_id,
                        'video_id': video_id,
                        'title': details.get('title', f'Video {video_id}'),
                        'url': f'https://youtube.com/watch?v={video_id}',
                        'date': details.get('publishedAt', '')[:10],
                        'transcript': transcript_text
                    })
                    
                    print(f"✓ Got transcript for: {video_id}")
                    
                except Exception as e:
                    failed.append({
                        'video_id': video_id,
                        'error': str(e)
                    })
                    print(f"✗ Failed for {video_id}: {str(e)}")
        
        return jsonify({
            'transcripts': transcripts,
            'failed': failed,
            'success_count': len(transcripts),
            'failed_count': len(failed)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def extract_channel_id(url):
    """Extract channel ID from various YouTube URL formats"""
    import re
    
    # Clean up the URL
    url = url.strip()
    
    # Pattern for channel ID (UC...)
    channel_id_pattern = r'youtube\.com/channel/(UC[\w-]+)'
    match = re.search(channel_id_pattern, url)
    if match:
        return match.group(1)
    
    # Pattern for @username - more flexible
    username_pattern = r'@([\w-]+)'
    match = re.search(username_pattern, url)
    if match:
        username = match.group(1)
        print(f"Found username: {username}")
        
        # Need to resolve username to channel ID using API
        try:
            youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
            
            # Search for the channel by username
            search_response = youtube.search().list(
                part='snippet',
                q=username,
                type='channel',
                maxResults=5
            ).execute()
            
            # Find exact match
            for item in search_response.get('items', []):
                channel_title = item['snippet']['channelTitle']
                if username.lower() in channel_title.lower().replace(' ', ''):
                    channel_id = item['snippet']['channelId']
                    print(f"Resolved to channel ID: {channel_id}")
                    return channel_id
            
            # If no exact match, try the first result
            if search_response.get('items'):
                channel_id = search_response['items'][0]['snippet']['channelId']
                print(f"Using first result: {channel_id}")
                return channel_id
                
        except Exception as e:
            print(f"Error resolving username: {e}")
            return None
    
    print(f"Could not extract channel info from: {url}")
    return None


if __name__ == '__main__':
    print("🚀 Starting YouTube Transcript Agent Backend...")
    print("📡 Server running on http://localhost:5000")
    app.run(debug=True, port=5001)