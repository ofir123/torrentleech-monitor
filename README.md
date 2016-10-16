TVDB Monitor
============

Follow all of your favorite TV shows easily, with Python!

TVDB Monitor keeps watch on all of your shows by querying the TVDB database and tell you about via E-Mail.  
It'll even tell you about upcoming seasons, so you'll never be caught off-guard.  
Every scan is saved in a little local JSON file, and updates are sent on changes since the last scan.

Usage
=====
Install the script as follows:

	$ python setup.py develop

Edit the shows file with your preferred shows:

	$ vim tvdb_monitor/shows.py
	
And set your account and E-Mail address in the settings file:

    $ vim tvdb_monitor/settings.py

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

    0 20 * * * python3 <TVDB_MONITOR_SCRIPT_PATH>
