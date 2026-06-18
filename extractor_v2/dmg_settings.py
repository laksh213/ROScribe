import os

# Volume name and output filename
volume_name = 'ROS Extractor System'
size = '4g'

# Place the app and a link to /Applications
files = ['dist/ROS Extractor System.app']
symlinks = {'Applications': '/Applications'}

icon_locations = {
    'ROS Extractor System.app': (120, 140),
    'Applications': (360, 140),
}

window_rect = ((200, 200), (480, 320))
default_view = 'icon-view'
background = 'builtin-arrow'
