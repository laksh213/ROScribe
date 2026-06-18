import os

# Volume name and output filename
volume_name = 'ROS Metadata Extractor'
size = '4g'

# We place the ROS_Extractor.app and link to /Applications
files = [ 'dist/ROS_Extractor.app' ]

symlinks = { 'Applications': '/Applications' }

# Layout settings: position of the app icon and Applications folder shortcut
icon_locations = {
    'ROS_Extractor.app': (120, 140),
    'Applications': (360, 140)
}

# Window size and position
window_rect = ((200, 200), (480, 320))
default_view = 'icon-view'
background = 'builtin-arrow'
