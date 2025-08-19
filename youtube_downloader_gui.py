import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pytube import YouTube
from pytube.exceptions import RegexMatchError, VideoUnavailable


class YouTubeDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Downloader")
        self.root.geometry("600x400")
        self.root.resizable(True, True)
        self.root.configure(padx=20, pady=20)
        
        # Set style
        self.style = ttk.Style()
        self.style.configure('TButton', font=('Arial', 10))
        self.style.configure('TLabel', font=('Arial', 11))
        self.style.configure('TEntry', font=('Arial', 10))
        
        # URL input
        ttk.Label(root, text="YouTube URL:", style='TLabel').grid(row=0, column=0, sticky=tk.W, pady=5)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(root, textvariable=self.url_var, width=50, style='TEntry')
        self.url_entry.grid(row=0, column=1, columnspan=2, sticky=tk.W+tk.E, pady=5, padx=5)
        
        # Output directory selection
        ttk.Label(root, text="Save to:", style='TLabel').grid(row=1, column=0, sticky=tk.W, pady=5)
        self.output_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self.output_entry = ttk.Entry(root, textvariable=self.output_var, width=40, style='TEntry')
        self.output_entry.grid(row=1, column=1, sticky=tk.W+tk.E, pady=5, padx=5)
        
        self.browse_btn = ttk.Button(root, text="Browse", command=self.browse_directory)
        self.browse_btn.grid(row=1, column=2, sticky=tk.W, pady=5, padx=5)
        
        # Video info frame
        self.info_frame = ttk.LabelFrame(root, text="Video Information")
        self.info_frame.grid(row=2, column=0, columnspan=3, sticky=tk.W+tk.E+tk.N+tk.S, pady=10, padx=0)
        self.info_frame.grid_columnconfigure(1, weight=1)
        
        # Video info labels
        ttk.Label(self.info_frame, text="Title:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.title_var = tk.StringVar(value="")
        ttk.Label(self.info_frame, textvariable=self.title_var, wraplength=400).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        ttk.Label(self.info_frame, text="Channel:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.channel_var = tk.StringVar(value="")
        ttk.Label(self.info_frame, textvariable=self.channel_var).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        ttk.Label(self.info_frame, text="Duration:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.duration_var = tk.StringVar(value="")
        ttk.Label(self.info_frame, textvariable=self.duration_var).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Action buttons
        self.fetch_btn = ttk.Button(root, text="Fetch Video Info", command=self.fetch_video_info)
        self.fetch_btn.grid(row=3, column=0, sticky=tk.W, pady=10)
        
        self.download_btn = ttk.Button(root, text="Download Video", command=self.start_download, state=tk.DISABLED)
        self.download_btn.grid(row=3, column=1, sticky=tk.W, pady=10, padx=5)
        
        # Progress bar
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress = ttk.Progressbar(root, orient=tk.HORIZONTAL, length=580, variable=self.progress_var, mode='determinate')
        self.progress.grid(row=4, column=0, columnspan=3, sticky=tk.W+tk.E, pady=5)
        
        # Status label
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(root, textvariable=self.status_var, style='TLabel')
        self.status_label.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        # Configure grid
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(2, weight=1)
        
        # Video object
        self.yt = None
        
    def browse_directory(self):
        directory = filedialog.askdirectory(initialdir=self.output_var.get())
        if directory:
            self.output_var.set(directory)
    
    def progress_callback(self, stream, chunk, bytes_remaining):
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        percentage = bytes_downloaded / total_size * 100
        self.progress_var.set(percentage)
        self.status_var.set(f"Downloading: {percentage:.1f}%")
        self.root.update_idletasks()
    
    def fetch_video_info(self):
        url = self.url_var.get()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return
        
        self.status_var.set("Fetching video information...")
        self.fetch_btn.configure(state=tk.DISABLED)
        
        def fetch_thread():
            try:
                self.yt = YouTube(url)
                
                # Update UI with video info
                self.title_var.set(self.yt.title)
                self.channel_var.set(self.yt.author)
                self.duration_var.set(f"{self.yt.length // 60}:{self.yt.length % 60:02d}")
                
                # Enable download button
                self.download_btn.configure(state=tk.NORMAL)
                self.status_var.set("Ready to download")
            
            except RegexMatchError:
                messagebox.showerror("Error", "Invalid YouTube URL.")
                self.status_var.set("Error: Invalid URL")
            except VideoUnavailable:
                messagebox.showerror("Error", "The video is unavailable.")
                self.status_var.set("Error: Video unavailable")
            except Exception as e:
                messagebox.showerror("Error", f"An error occurred: {str(e)}")
                self.status_var.set(f"Error: {str(e)}")
            finally:
                self.fetch_btn.configure(state=tk.NORMAL)
        
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def start_download(self):
        if not self.yt:
            messagebox.showerror("Error", "Please fetch video information first")
            return
        
        output_path = self.output_var.get()
        self.download_btn.configure(state=tk.DISABLED)
        self.fetch_btn.configure(state=tk.DISABLED)
        self.status_var.set("Starting download...")
        self.progress_var.set(0)
        
        def download_thread():
            try:
                # Register progress callback
                self.yt.register_on_progress_callback(self.progress_callback)
                
                # Filter for mp4 streams with 1080p resolution
                streams = self.yt.streams.filter(file_extension='mp4', res='1080p', progressive=False)
                if not streams:
                    streams = self.yt.streams.filter(file_extension='mp4', progressive=True)
                    self.status_var.set("1080p MP4 not available. Downloading highest quality available.")
                
                video_stream = streams.order_by('resolution').desc().first()
                
                if not video_stream:
                    messagebox.showerror("Error", "No suitable video stream found.")
                    self.status_var.set("Error: No suitable video stream found")
                    return
                
                # Download the video
                out_file = video_stream.download(output_path=output_path)
                self.status_var.set(f"Download complete! Saved to: {os.path.basename(out_file)}")
                messagebox.showinfo("Success", f"Download complete!\nSaved to: {out_file}")
            
            except Exception as e:
                messagebox.showerror("Error", f"An error occurred: {str(e)}")
                self.status_var.set(f"Error: {str(e)}")
            finally:
                self.download_btn.configure(state=tk.NORMAL)
                self.fetch_btn.configure(state=tk.NORMAL)
        
        threading.Thread(target=download_thread, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = YouTubeDownloaderApp(root)
    root.mainloop() 