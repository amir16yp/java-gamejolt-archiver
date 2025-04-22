import cloudscraper
import json
import re
import os
import urllib.parse
import argparse
import sys
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs
from pathlib import Path

class GameJoltArchiver:
    BASE_URL = "https://gamejolt.com"
    GAME_API_URL = "https://gamejolt.com/site-api/web/discover/games/overview/{}?ignore"
    BUILD_API_URL = "https://gamejolt.com/site-api/web/discover/games/builds/get-download-url/{}"
    GAMESERVER_API_URL = "https://gamejolt.net/site-api/gameserver/{}"
    
    def __init__(self, download_dir="downloads", verbose=True):
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            }
        )
        # Set up additional headers
        self.session.headers.update({
            'Accept-Language': 'en-GB,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Origin': 'https://gamejolt.com',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
            'DNT': '1',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'TE': 'trailers'
        })
        
        # Create download directory
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)
        self.verbose = verbose
    
    def print_json_response(self, data: Dict[str, Any], prefix: str = "") -> None:
        """
        Pretty print JSON response data.
        
        Args:
            data: JSON data to print
            prefix: Optional prefix for the output
        """
        if not self.verbose:
            return
            
        if prefix:
            print(f"\n{prefix}:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print()  # Add blank line after JSON output

    def format_timestamp(self, timestamp: int) -> str:
        """Convert millisecond timestamp to readable date"""
        return datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
    
    def extract_game_id_from_url(self, url: str) -> Optional[int]:
        """
        Extract game ID from a GameJolt URL.
        
        Args:
            url (str): GameJolt game URL
            
        Returns:
            Optional[int]: Game ID if found, None otherwise
        """
        try:
            # Parse the URL
            parsed_url = urlparse(url)
            
            # Verify it's a GameJolt URL
            if not parsed_url.netloc.endswith('gamejolt.com'):
                return None
                
            # Extract the path
            path = parsed_url.path.strip('/').split('/')
            
            # Check for game URL patterns
            if len(path) >= 3 and path[0] == 'games':
                # Pattern: /games/game-slug/12345
                if path[-1].isdigit():
                    return int(path[-1])
                    
                # Pattern: /games/game-slug/ID
                game_id_match = re.search(r'/games/[^/]+/(\d+)/?', parsed_url.path)
                if game_id_match:
                    return int(game_id_match.group(1))
            
            return None
            
        except Exception as e:
            print(f"Error extracting game ID from URL: {str(e)}")
            return None
    
    def get_game_info(self, game_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch game information from GameJolt API.
        
        Args:
            game_id (int): The numeric ID of the game to fetch
            
        Returns:
            Optional[Dict[str, Any]]: Game information if successful, None if failed
        """
        try:
            # Update headers for API request
            self.session.headers.update({
                'Accept': 'application/json, text/plain, */*',
                'Referer': f'{self.BASE_URL}/games/game/{game_id}',
                'X-Requested-With': 'XMLHttpRequest'
            })
            
            response = self.session.get(self.GAME_API_URL.format(game_id))
            response.raise_for_status()
            
            data = response.json()
            self.print_json_response(data, f"Game API Response (ID: {game_id})")
            
            if "payload" in data:
                return data["payload"]
            return None
            
        except Exception as e:
            print(f"Error fetching game {game_id}: {str(e)}")
            return None

    def extract_token_from_url(self, url: str) -> Optional[str]:
        """
        Extract token from download URL.
        
        Args:
            url (str): URL that may contain a token parameter
            
        Returns:
            Optional[str]: Token if found, None otherwise
        """
        try:
            # First check if the URL has a query parameter "token"
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            
            if 'token' in query_params:
                return query_params['token'][0]
            
            # Otherwise, check if it's a direct token URL like https://gamejolt.net/?token=XYZ
            if parsed_url.netloc == 'gamejolt.net' and not parsed_url.path:
                query_params = parse_qs(parsed_url.query)
                if 'token' in query_params:
                    return query_params['token'][0]
                    
            return None
            
        except Exception as e:
            print(f"Error extracting token from URL: {str(e)}")
            return None

    def get_build_download_url(self, build_id: str, game_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the download information for a specific build.
        
        Args:
            build_id (str): The build ID to fetch
            game_id (int): The game ID for the referer header
            
        Returns:
            Optional[Dict[str, Any]]: Download information if successful, None if failed
        """
        try:
            # First get the initial URL with token
            self.session.headers.update({
                'Accept': 'image/webp,*/*',
                'Referer': f'{self.BASE_URL}/games/{game_id}',
                'Alt-Used': 'gamejolt.com'
            })
            
            response = self.session.post(
                self.BUILD_API_URL.format(build_id),
                json={},  # Empty JSON payload
                headers=self.session.headers
            )
            response.raise_for_status()
            
            initial_data = response.json()
            self.print_json_response(initial_data, f"Initial Build API Response (ID: {build_id})")
            
            # Extract the token or URL with token
            if "payload" in initial_data and "url" in initial_data["payload"]:
                initial_url = initial_data["payload"]["url"]
                token = self.extract_token_from_url(initial_url)
                
                if token:
                    # Now get the actual download information using the token
                    gameserver_response = self.session.get(self.GAMESERVER_API_URL.format(token))
                    gameserver_response.raise_for_status()
                    
                    gameserver_data = gameserver_response.json()
                    self.print_json_response(gameserver_data, f"Gameserver API Response (Token: {token})")
                    
                    return gameserver_data.get("payload", {})
                else:
                    print(f"No token found in URL: {initial_url}")
            
            return None
            
        except Exception as e:
            print(f"Error fetching build {build_id}: {str(e)}")
            return None

    def get_file_details(self, download_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract file details from download info.
        
        Args:
            download_info (Dict[str, Any]): Download information from the gameserver API
            
        Returns:
            Dict[str, Any]: File information including download URL, filename, and other metadata
        """
        result = {}
        
        if "url" in download_info:
            result["download_url"] = download_info["url"]
        
        if "build" in download_info and "primary_file" in download_info["build"]:
            primary_file = download_info["build"]["primary_file"]
            result["filename"] = primary_file.get("filename")
            result["filesize"] = primary_file.get("filesize")
        
        if "build" in download_info:
            build = download_info["build"]
            result["build_id"] = build.get("id")
            result["type"] = build.get("type")
            result["added_on"] = build.get("added_on")
            result["updated_on"] = build.get("updated_on")
            
            # Platform information
            platforms = []
            if build.get("os_windows"): platforms.append("Windows")
            if build.get("os_mac"): platforms.append("Mac")
            if build.get("os_linux"): platforms.append("Linux")
            if build.get("os_other"): platforms.append("Other")
            result["platforms"] = platforms
            
            # Get embed dimensions if available
            if build.get("embed_width"):
                result["width"] = build.get("embed_width")
            if build.get("embed_height"):
                result["height"] = build.get("embed_height")
            
        if "game" in download_info:
            game = download_info["game"]
            result["game_id"] = game.get("id")
            result["title"] = game.get("title")
            
        # Additional information for Java applets
        if download_info.get("javaArchive"):
            result["java_archive"] = download_info.get("javaArchive")
            result["java_codebase"] = download_info.get("javaCodebase")
            
            if "build" in download_info and download_info["build"].get("java_class_name"):
                result["java_class_name"] = download_info["build"].get("java_class_name")
        
        return result
        
    def download_file(self, url: str, filename: str, game_title: str, output_path: Optional[str] = None) -> Tuple[bool, str]:
        """
        Download a file from a URL and save it to the downloads directory.
        
        Args:
            url (str): The URL to download from
            filename (str): The filename to save as
            game_title (str): The title of the game (for creating a subdirectory)
            output_path (Optional[str]): Specific output path to use instead of default
            
        Returns:
            Tuple[bool, str]: (Success status, Path to the downloaded file or error message)
        """
        try:
            # Determine output path
            if output_path:
                # Ensure the directory exists
                os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
                final_output_path = output_path
            else:
                # Create game-specific directory (slugified)
                game_dir = self.create_game_directory(game_title)
                final_output_path = os.path.join(game_dir, filename)
            
            # Check if file already exists
            if os.path.exists(final_output_path):
                print(f"File already exists: {final_output_path}")
                return True, final_output_path
                
            # Update session headers for file download
            self.session.headers.update({
                'Accept': '*/*',
                'Referer': self.BASE_URL
            })
            
            # Stream the download to handle large files efficiently
            with self.session.get(url, stream=True) as response:
                response.raise_for_status()
                
                # Show download progress
                total_size = int(response.headers.get('content-length', 0))
                print(f"Downloading {filename} ({self.format_filesize(total_size)})...")
                
                # Save the file
                with open(final_output_path, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            self.show_progress(downloaded, total_size)
                
                print(f"\nDownloaded to: {final_output_path}")
                return True, final_output_path
                
        except Exception as e:
            error_msg = f"Error downloading file: {str(e)}"
            print(error_msg)
            return False, error_msg
    
    def create_game_directory(self, game_title: str) -> str:
        """Create a directory for the game files using a safe version of the title"""
        # Create a safe directory name
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in game_title)
        safe_title = safe_title.strip().replace(" ", "_")
        
        # Create the directory
        game_dir = os.path.join(self.download_dir, safe_title)
        os.makedirs(game_dir, exist_ok=True)
        
        return game_dir
        
    def format_filesize(self, size_in_bytes: int) -> str:
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.2f} {unit}"
            size_in_bytes /= 1024.0
        return f"{size_in_bytes:.2f} TB"
        
    def show_progress(self, downloaded: int, total: int) -> None:
        """Show download progress"""
        if total > 0:
            percent = int(100 * downloaded / total)
            bar_length = 30
            filled_length = int(bar_length * percent / 100)
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            print(f"\r|{bar}| {percent}% ({self.format_filesize(downloaded)}/{self.format_filesize(total)})", end='')
            
    def create_cheerpj_html(self, file_details: Dict[str, Any], output_dir: str) -> Tuple[bool, str]:
        """
        Create an HTML file for running a Java applet using CheerpJ in modern browsers.
        
        Args:
            file_details (Dict[str, Any]): File details containing Java applet information
            output_dir (str): Directory to save the HTML file
            
        Returns:
            Tuple[bool, str]: (Success status, Path to the HTML file or error message)
        """
        try:
            # Check if we have the necessary information
            if 'java_class_name' not in file_details or 'filename' not in file_details:
                return False, "Missing Java class name or filename in file details"
                
            # Get file details
            jar_filename = file_details.get('filename')
            java_class = file_details.get('java_class_name')
            game_title = file_details.get('title', 'Game')
            
            # Get dimensions or use defaults
            width = file_details.get('width', 640)
            height = file_details.get('height', 480)
            
            # Create HTML file
            html_filename = os.path.join(output_dir, "cheerpj.html")
            
            with open(html_filename, 'w', encoding='utf-8') as f:
                f.write(f'''<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{game_title} - CheerpJ Applet</title>
    <script src="https://cjrtnc.leaningtech.com/4.0/loader.js"></script>
    <style>
      body {{
        font-family: Arial, sans-serif;
        max-width: 1000px;
        margin: 0 auto;
        padding: 20px;
        background: #f5f5f5;
      }}
      h1 {{
        color: #333;
      }}
      .container {{
        background: white;
        padding: 20px;
        border-radius: 5px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        margin-bottom: 20px;
      }}
      .instructions {{
        background: #f0f8ff;
        padding: 15px;
        border-left: 4px solid #0066cc;
        margin: 20px 0;
      }}
    </style>
  </head>
  <body>
    <div class="container">
      <h1>{game_title}</h1>
      <div class="instructions">
        <p>This Java applet is running through CheerpJ, a Java runtime for browsers.</p>
        <p>It may take a moment to load. If you experience issues:</p>
        <ul>
          <li>Make sure you're using a modern browser (Chrome, Firefox, Edge)</li>
          <li>Try refreshing the page if the applet doesn't start</li>
          <li>Allow pop-ups if prompted</li>
        </ul>
      </div>
      <applet
        archive="{jar_filename}"
        code="{java_class}"
        height="{height}"
        width="{width}"
      ></applet>
    </div>
    <script>
      cheerpjInit();
    </script>
  </body>
</html>''')
                
            print(f"Created CheerpJ HTML file: {html_filename}")
            return True, html_filename
            
        except Exception as e:
            error_msg = f"Error creating CheerpJ HTML file: {str(e)}"
            print(error_msg)
            return False, error_msg

def process_game(game_id: int, output_path: Optional[str] = None, verbose: bool = False, 
                 print_java_class: bool = False, download: bool = True,
                 create_cheerpj: bool = False) -> None:
    """
    Process a game by ID, downloading if requested.
    
    Args:
        game_id (int): The game ID to process
        output_path (Optional[str]): Specific output path for downloads
        verbose (bool): Whether to print verbose output
        print_java_class (bool): Whether to print Java class info
        download (bool): Whether to download the game files
        create_cheerpj (bool): Whether to create CheerpJ HTML files for Java applets
    """
    archiver = GameJoltArchiver(verbose=verbose)
    
    # Get game info
    game_info = archiver.get_game_info(game_id)
    if not game_info:
        print(f"Failed to retrieve game with ID {game_id}")
        return
        
    game_title = game_info['microdata']['name']
    print(f"\nGame: {game_title} (ID: {game_id})")
    print(f"URL: {game_info['microdata']['url']}")
    
    if verbose:
        print(f"Description: {game_info['microdata']['description']}")
        
        if 'aggregateRating' in game_info['microdata']:
            rating = game_info['microdata']['aggregateRating']
            print(f"\nRatings: {rating['ratingValue']:.2f}/1.0 ({rating['ratingCount']} ratings)")
        
        print(f"Stats: {game_info['profileCount']} views, {game_info['downloadCount']} downloads, {game_info['playCount']} plays")
    
    # Process builds
    if game_info.get('builds'):
        jar_files = []
        java_class_info = []
        
        for build in game_info['builds']:
            if verbose:
                print(f"\nBuild ID: {build['id']}")
                if build.get('primary_file'):
                    print(f"File: {build['primary_file']['filename']} ({archiver.format_filesize(int(build['primary_file']['filesize']))})")
                print(f"Type: {build['type']}")
                platforms = []
                if build.get('os_windows'): platforms.append("Windows")
                if build.get('os_mac'): platforms.append("Mac")
                if build.get('os_linux'): platforms.append("Linux")
                if build.get('os_other'): platforms.append("Other")
                if platforms:
                    print(f"Platforms: {', '.join(platforms)}")
                print(f"Added: {archiver.format_timestamp(build['added_on'])}")
            
            # Get download information
            download_info = archiver.get_build_download_url(build['id'], game_id)
            if download_info:
                file_details = archiver.get_file_details(download_info)
                
                # Store Java class information if available
                if 'java_class_name' in file_details and (print_java_class or create_cheerpj):
                    java_info = {
                        'filename': file_details.get('filename', ''),
                        'java_class': file_details.get('java_class_name', ''),
                        'java_archive': file_details.get('java_archive', ''),
                        'java_codebase': file_details.get('java_codebase', ''),
                        'title': game_title,
                        'width': file_details.get('width', 640),
                        'height': file_details.get('height', 480)
                    }
                    java_class_info.append(java_info)
                
                # Check if it's a JAR file
                filename = file_details.get('filename', '')
                if download and filename.lower().endswith('.jar'):
                    jar_files.append((file_details.get('download_url'), filename))
                    
                    if verbose:
                        print(f"JAR file detected: {filename}")
                        
                    # Download the file
                    if download:
                        # Determine output directory
                        output_dir = os.path.dirname(output_path) if output_path else archiver.create_game_directory(game_title)
                        
                        success, jar_path = archiver.download_file(
                            file_details.get('download_url'),
                            filename,
                            game_title,
                            output_path
                        )
                        
                        # Create CheerpJ HTML file if requested and it's a Java applet
                        if create_cheerpj and success and 'java_class_name' in file_details:
                            archiver.create_cheerpj_html(
                                {**file_details, 'title': game_title},
                                os.path.dirname(jar_path)
                            )
        
        # Print Java class information if requested
        if print_java_class and java_class_info:
            print("\nJava Class Information:")
            for info in java_class_info:
                print(f"File: {info['filename']}")
                print(f"Class: {info['java_class']}")
                print(f"Archive: {info['java_archive']}")
                print(f"Codebase: {info['java_codebase']}")
                print(f"Dimensions: {info['width']}x{info['height']}")
                print("---")
                
        if not jar_files and download:
            print("No JAR files found for this game.")
    else:
        print("No builds found for this game.")

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='GameJolt Archiver - Download games from GameJolt')
    
    # Game identification
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-g', '--game-id', type=int, help='GameJolt game ID')
    group.add_argument('-u', '--url', type=str, help='GameJolt game URL')
    
    # Output options
    parser.add_argument('-o', '--output', type=str, help='Output file path (for single file downloads)')
    parser.add_argument('-d', '--download-dir', type=str, default='downloads', 
                        help='Directory to store downloads (default: downloads)')
    
    # Behavior options
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('-j', '--java-class', action='store_true', help='Print Java class information')
    parser.add_argument('-n', '--no-download', action='store_true', help='Don\'t download files, just print info')
    parser.add_argument('-c', '--cheerpj', action='store_true', 
                        help='Generate CheerpJ HTML file for running Java applets in modern browsers')
    
    args = parser.parse_args()
    
    # Determine game ID
    game_id = None
    if args.game_id:
        game_id = args.game_id
    elif args.url:
        archiver = GameJoltArchiver(download_dir=args.download_dir, verbose=args.verbose)
        game_id = archiver.extract_game_id_from_url(args.url)
        if not game_id:
            print(f"Could not extract game ID from URL: {args.url}")
            sys.exit(1)
    
    # Process the game
    process_game(
        game_id=game_id,
        output_path=args.output,
        verbose=args.verbose,
        print_java_class=args.java_class,
        download=not args.no_download,
        create_cheerpj=args.cheerpj
    )

if __name__ == "__main__":
    main()
