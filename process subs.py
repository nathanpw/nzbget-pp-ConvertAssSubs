#!/usr/bin/env python3
#
##############################################################################
### NZBGET POST-PROCESSING SCRIPT                                          ###

# A post process plugin for NZBGet which will convert ASS subs to SRT, and
# removes dvb and pgs subtitles.
#
# NOTE: This script requires Python to be installed on your system.
# Requires:
# - ffmpeg-python (pip install ffmpeg-python) and ffmpeg
# - filedate (pip install filedate)
# Linux only!

##############################################################################
### OPTIONS                                                                ###

### NZBGET POST-PROCESSING SCRIPT                                          ###
##############################################################################

import os
import sys
import ffmpeg
import filedate
import subprocess
from pymkv import MKVFile
# for printing Python dictionaries in a human-readable way
from pprint import pprint

# Should be false, except when debugging/testing outside nzbget.
skipNZBChecks=False

# NZBGet V11+
# Check if the script is called from nzbget 11.0 or later
if skipNZBChecks or 'NZBOP_SCRIPTDIR' in os.environ and not os.environ['NZBOP_VERSION'][0:5] < '11.0':
    # Exit codes used by NZBGet
    POSTPROCESS_PARCHECK=92
    POSTPROCESS_SUCCESS=93
    POSTPROCESS_ERROR=94
    POSTPROCESS_NONE=95

    # Allow debugging mode when skipNZBChecks is true.
    if skipNZBChecks:
        print ("[INFO] Script triggered from outisde NZBGet.")
        # Define variables for testing outside of nzbget.
        process_directory = "/home/nate/Videos/test"
        print ("[INFO] Option variables set.")
    else:
        print ("[INFO] Script triggered from NZBGet (11.0 or later).")
        # Check if destination directory exists (important for reprocessing of history items)
        if not os.path.isdir(os.environ['NZBPP_DIRECTORY']):
            print ("[ERROR] Nothing to post-process: destination directory", os.environ['NZBPP_DIRECTORY'], "doesn't exist")
            sys.exit(POSTPROCESS_ERROR)
        process_directory=os.environ['NZBPP_DIRECTORY']
        print ("[INFO] Option variables set.")

    # Set the option variables.
    # TODO: Make these configurable options and test?
    extensionsToProcess = []
    extensionsToProcess.append(".mkv")
    codecToConvert = []
    codecToConvert.append("ass")
    # TODO: Make these configurable options and test?
    codecsToRemove = []
    codecsToRemove.append("dvb_subtitle")
    codecsToRemove.append("dvd_subtitle")
    codecsToRemove.append("hdmv_pgs_subtitle")

    # Helper function to get file path, name, and extension
    def getFilePathinfo(file):
        file_path = os.path.dirname(file)
        file_name = os.path.basename(file)
        file_name, file_extension = os.path.splitext(file_name)
        return file_path, file_name, file_extension

    # Helper function to get sub stream info.
    def getSubStreams(file):
        # Get video info with ffprobe
        probe = ffmpeg.probe(file)
        stream_data = probe
        sub_streams = []
        for stream in probe['streams']:
            if stream['codec_type'] == 'subtitle':
                sub_streams.append(stream)
        return sub_streams

    # Helper function to get a new and unsused file name with mkv extension.
    def getNewFileName(file, counter=1, ext=".mkv"):
        file_path, file_name, file_extension = getFilePathinfo(file)
        new_file=file_name+"("+str(counter)+")"+ext
        if os.path.exists(os.path.join(file_path, new_file)):
            counter += 1
            new_file = getNewFileName(file, counter)
        return os.path.join(file_path, new_file)

    # Helper function to get a file's dates.
    def getFileDates(file):
        # Return the files dates in a dict.
        file_date = filedate.File(file)
        dates = file_date.get()
        return dates

    # Helper function to set a file's dates.
    def setFileDates(file, dates):
        new_file_date = filedate.File(file)
        new_dates = new_file_date.get()
        new_file_date.set(
            created = new_dates['created'],
            modified = dates['modified'],
            accessed = dates['accessed']
        )

    # Helper function to process subs with ffmpeg, returns new converted file or
    # False if it failed.
    def processSubs(file, subsToKeep):
        new_file=getNewFileName(file)
        # Produces something like.:
        # ffmpeg -i file.mkv -map 0 -c:v copy -c:a copy -c:s srt out.mkv
        # Set the kwargs for output.
        kwargs={}
        # Copy all video.
        kwargs['c:v'] = 'copy'
        # Copy all audio.
        kwargs['c:a'] = 'copy'
        # Convert all subs to SRT.
        kwargs['c:s'] = 'srt'
        #TODO Remove chapters and tags?

        # Start converting with ffmpeg.
        try:
            # Set input, video, audio, and subs (for mappings)
            mkv = ffmpeg.input(file)
            video = mkv['v']
            audio = mkv['a']
            subs = []
            if len(subsToKeep) > 0:
                for subID in subsToKeep:
                    subs.append(mkv['s:' + str(subID)])

            # Uncomment for debugging to see ffmpeg options.
            #command_args = ( ffmpeg
            #    .output(video, audio, *subs, new_file, **kwargs)
            #)
            #print(ffmpeg.get_args(command_args))

            print("[INFO] Processing file:", file)
            out, err = ( ffmpeg
                .output(video, audio, *subs, new_file, **kwargs)
                .overwrite_output()
                #.run(capture_stdout=True)
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )
        except ffmpeg.Error as e:
            # Uncomment for troubleshooting? I found `sudo dmesg` to be
            # better, particularly if ffmpeg is segfaulting.
            #print(e.stderr, file=sys.stderr)
            # Remove new file if it exists.
            if os.path.isfile(new_file):
                os.remove(new_file)
            print ("[ERROR] ffmpeg error converting file:", file)
            return False
        else:
            print ("[INFO] Processed file:", file)
            return new_file

    # Get all the files we will need to process and the stream details.
    files_to_process = {}
    files_checked = 0
    print ("[INFO] Checking directory:", process_directory)
    for dir_path, dir_names, file_names in os.walk(process_directory):
        for file in file_names:
            file_path, file_name, file_extension = getFilePathinfo(file)
            fullfile_path=os.path.join(dir_path, file)
            if file_extension in extensionsToProcess:
                files_checked += 1
                # Get info with ffprobe
                sub_data = getSubStreams(fullfile_path)
                for stream in sub_data:
                    if stream['codec_name'] in codecToConvert or stream['codec_name'] in codecsToRemove:
                        files_to_process[fullfile_path] = sub_data
    print ("[INFO] Checked " + str(files_checked) + " files")
    print ("[INFO] Found", len(files_to_process), "files to process.")

    # Process files and continue on failure, while keeping track of one or more failures.
    failed = False
    for file, streams in files_to_process.items():
        # Keep track of the subid and find any subs to keep.
        subID = 0
        subsToKeep = []
        for stream in streams:
            if stream['codec_name'] not in codecsToRemove:
                subsToKeep.append(str(subID))
            subID += 1
        print("[INFO] Processing file:", file)
        new_file = False
        # Start ffmpeg.
        new_file = processSubs(file, subsToKeep)
        # If the new file doesn't exist mark a failure.
        if not new_file:
            failed = True
        elif os.path.isfile(new_file):
            # Otherwise maintain the file modifed and accessed dates.
            old_dates = getFileDates(file)
            setFileDates(new_file, old_dates)
            # Move the new file in place.
            print("[INFO] Removing file:", file)
            os.remove(file)
            print("[INFO] Moving file:", new_file, "to: ", file)
            os.rename(new_file, file)
    # Check if a file failed and exit approriately.
    if failed:
        print ("[ERROR] Completed with atleast 1 failed convertion.")
        sys.exit(POSTPROCESS_ERROR)
    else:
        print ("[INFO] Completed all convertions.")
        sys.exit(POSTPROCESS_SUCCESS)
