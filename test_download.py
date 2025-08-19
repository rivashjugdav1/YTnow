from pytube import YouTube

# URL of a different video to download (Rick Astley - Never Gonna Give You Up)
url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

try:
    # Create a YouTube object
    yt = YouTube(url)
    
    # Print video information
    print(f"Title: {yt.title}")
    print(f"Length: {yt.length} seconds")
    print(f"Author: {yt.author}")
    
    # Get available streams
    print("\nAvailable MP4 streams:")
    for stream in yt.streams.filter(file_extension='mp4'):
        print(f"Resolution: {stream.resolution}, Type: {stream.mime_type}, Progressive: {stream.is_progressive}")
    
    # Get the highest resolution mp4 stream
    stream = yt.streams.filter(file_extension='mp4').order_by('resolution').desc().first()
    
    if stream:
        print(f"\nDownloading: {stream.resolution} {stream.mime_type}")
        stream.download()
        print("Download complete!")
    else:
        print("No suitable stream found.")
    
except Exception as e:
    print(f"An error occurred: {str(e)}") 