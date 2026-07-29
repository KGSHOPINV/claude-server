# Linux Survival Guide

## Navigation

```bash
pwd                    # where am I?
ls                     # list files
ls -la                 # list ALL files with details
cd /path/to/folder     # go to folder
cd ..                  # go up one level
cd ~                   # go to home folder
```

## Files

```bash
cat file.txt           # read a file
nano file.txt          # edit a file (Ctrl+X to save/exit)
cp file.txt backup.txt # copy
mv old.txt new.txt     # rename/move
rm file.txt            # delete (no undo!)
mkdir foldername       # create folder
rm -rf foldername      # delete folder and everything in it (DANGEROUS)
```

## System

```bash
htop                   # live CPU/RAM monitor (q to quit)
df -h                  # disk space
free -h                # RAM usage
uptime                 # how long server has been running
reboot                 # restart server (need sudo)
```

## Permissions

```bash
sudo command           # run as admin
chmod +x script.sh     # make a file executable
chown user:group file  # change file owner
```

## Searching

```bash
grep "text" file.txt           # find text in a file
grep -r "text" /path/          # find text in all files in a folder
find / -name "filename"        # find a file by name
```

## Network

```bash
ip a                           # show IP addresses
ping 8.8.8.8                   # test internet connection
curl http://localhost:3000     # test if a service responds
ss -tlnp                       # show what ports are open
```

## Package Management

```bash
sudo apt update                # refresh package list
sudo apt upgrade               # update installed packages
sudo apt install package-name  # install something
sudo apt remove package-name   # uninstall something
```

## Shortcuts

| Key | What it does |
|-----|-------------|
| Ctrl+C | Stop/cancel current command |
| Ctrl+D | Exit/logout |
| Ctrl+L | Clear screen |
| Tab | Auto-complete file/folder names |
| Up arrow | Previous command |
| history | Show command history |
```
