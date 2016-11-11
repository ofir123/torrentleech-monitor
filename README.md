TorrentLeech Monitor
============

Follow all of your favorite TV shows easily, with Python!

TorrentLeech Monitor keeps watch on all of your shows by querying the TVDB database and tell you about it via E-Mail.

Every scan is saved in a little local JSON file, and updates are sent on available new episodes since the last scan.

Each scan result can then be downloaded from TorrentLeech, to automate the process.

Usage
=====
Install the script as follows:

	$ python setup.py develop

Edit the shows file with your preferred shows:

	$ vim torrentleech_monitor/shows.py
	
And set your account and E-Mail address in the settings file:

    $ vim torrentleech_monitor/settings.py

Notice that you have to set on the "less secure apps" option in the selected GMail account.  
You can do it easily from here: https://www.google.com/settings/security/lesssecureapps

And that's it!

The script can now run from command line:

	$ tvdb_monitor
	
Automatic Monitoring
====================
The easiest way to configure automatic monitoring, is by using crontab:
    
    $ crontab -e

There, add the following line, to get show updates every day at 8 PM (or any other hour you like):

    0 20 * * * python3 <TORRENTLEECH_MONITOR_SCRIPT_PATH>
