# USB key backup with Ansible

The laptop (Debian) is the Ansible control node: this is where the USB keys are plugged in.
The storage server (Debian) receives the backups in:

    /srv/usb-backup/teams/<team>/<key>/<project>/<timestamp>/        content of the key
    /srv/usb-backup/teams/<team>/<key>/<project>/<timestamp>.sha256  checksums

Seen by a team (web or FileZilla), this is `/<team>/<key>/<project>/<timestamp>`.

## Requirements

Only the Debian 13 "main" repositories (no external repository, no contrib/non-free, no pip).
Tested end to end with the Debian 13 versions: ansible 12.0.0 (ansible-core 2.19.4,
ansible.posix 2.1.0, community.general 11.2.1), Python 3.13, python3-passlib 1.7.4.

Laptop: `sudo apt install ansible rsync python3-passlib openssh-client sudo`
(optional: `ntfs-3g` for NTFS keys, `git`)
(the `ansible` package includes the `ansible.posix` and `community.general` collections;
otherwise: `ansible-galaxy collection install -r requirements.yml`).

Server: `sudo apt install openssh-server sudo python3 python3-apt`, and an administration
account reachable over SSH and member of the `sudo` group. Everything else (rsync, nginx,
openssl, python3-passlib, ...) is installed by `setup_server.yml`.

Edit `inventory/hosts.yml` (server IP, `ansible_user`). Use the real IP of the server, never
`127.0.0.1`: with a loopback address the copy module thinks the server is the laptop itself.

## 0. Secrets (Ansible Vault)

The sudo passwords are stored encrypted in the `vault/` folder, **not** in `group_vars`.
A `group_vars` file would be loaded by every playbook: the person running the backups would
then need the vault password, and could read the server admin password. Here, each playbook
only loads what it needs.

| File | Content | Loaded by | Required |
|---|---|---|---|
| `vault/admin.yml` | `vault_admin_become_password`: sudo password of the server admin account | `setup_server.yml`, `create_team.yml` | yes |
| `vault/laptop.yml` | `vault_laptop_become_password`: sudo password of the laptop, to mount a key | `backup_usb.yml` | no |

Creation (the file opens in an editor and is encrypted when saved):

    ansible-vault create vault/admin.yml
    # content: vault_admin_become_password: "the-password"   (see vault/admin.yml.example)

    ansible-vault create vault/laptop.yml        # optional

Using **two different vault passwords** for `admin.yml` and `laptop.yml` is recommended when
the people who administer the server are not the ones who run the backups.

Useful commands:

    ansible-vault edit  vault/admin.yml     # edit
    ansible-vault view  vault/admin.yml     # read
    ansible-vault rekey vault/admin.yml     # change the vault password

By default the vault password is asked at each run (`--ask-vault-pass`).
To stop typing it, preferably on a laptop with an encrypted disk:

    mkdir -p ~/.config/usb-backup
    ( umask 077; echo 'the-vault-password' > ~/.config/usb-backup/vault_pass )

then uncomment `vault_password_file` in `ansible.cfg`. This file is **outside the repository**.

Before each run, the `usb_backup_vault` role checks that the required files exist, that they
are **encrypted** (plain-text files are rejected) and that they contain the right variables.

### Git

Encrypted `vault/*.yml` files may be committed. The `.gitignore` excludes vault password
files and private keys. Enable the hook that rejects any commit of an unencrypted vault file
(once per clone):

    git config core.hooksPath tools/git-hooks

## 1. Install the server (once)

    ansible-playbook setup_server.yml --ask-vault-pass

This playbook also generates, on the laptop, the SSH key `~/.ssh/usb_backup_ed25519` of the
copy account.

## 2. Create a team

    ansible-playbook create_team.yml --ask-vault-pass

Asks for the team name and password. Running it again with the same name changes the password.
(A team password is typed in, never stored in the project: the server only keeps a hash of it,
for SSH/SFTP and for nginx.)

## 3. Back up a key

    ansible-playbook backup_usb.yml                    # key already mounted by the desktop
    ansible-playbook backup_usb.yml --ask-vault-pass   # if vault/laptop.yml exists
    ansible-playbook backup_usb.yml -K                 # no vault/laptop.yml, key not mounted

Questions asked: team -> key among the plugged-in ones -> key name -> project -> confirmation.
The server is reached with the SSH key of the copy account: no server password is used, and
`vault/admin.yml` is never loaded. The laptop sudo password is only used to mount a key that
the desktop did not mount; the key is then mounted read-only and unmounted at the end.

At the end, the playbook compares the SHA-256 of every file on the key with the files actually
stored, and fails on any mismatch.

Before copying, the playbook shows the number of files and the total size of the key. The copy
itself shows no progress until it is finished: with a slow key or many files, it can stay on
"Copy the content of the key to the server (rsync)" for several minutes. To check that it is
moving, run on the server `watch -n 2 'sudo du -sh /srv/usb-backup/incoming/*'`.

If no data moves for 300 seconds (stalled key, USB port or network), rsync stops and the
playbook fails with a clear message. This is not a limit on the total duration: a long copy
that keeps moving is never interrupted. Change the delay with the `usb_backup_rsync_timeout`
variable, for example `-e usb_backup_rsync_timeout=600`. In case of a stall, look for USB
errors with `sudo dmesg`, try another port or key, and prefer a wired network.

If you stop the playbook with Ctrl+C, the final cleanup does not run: delete the leftover
folder in `/srv/usb-backup/incoming/` and, if the playbook had mounted the key, run
`sudo umount /mnt/usb-backup/*` then `sudo rmdir /mnt/usb-backup/*`.

## Team access

* Web: `https://<server>/`, enter the team name, then its password.
  Self-signed certificate: the browser shows a warning the first time.
* FileZilla: **SFTP** protocol, host `<server>`, port 22, user = team name.
  The team lands directly in `/<team>` and can delete its files.

## Permissions

| Account | Write a backup | Read the backups | Delete |
|---|---|---|---|
| `svc_backup` (copy account) | yes, through its transfer area | no | no |
| team | through SFTP | its own only | its own only |
| `www-data` (nginx) | no | yes, filtered by team password | no |

The copy account writes into `incoming/` (its own area), then runs through sudo the only
script it is allowed to, `/usr/local/sbin/usb-backup-finalize`, which validates the arguments,
hands the files over to the team, stores them and computes the checksums. It has no read
access to `teams/`.

## Delete a team (manual)

    sudo userdel <team> && sudo groupdel <team>
    sudo rm -rf /srv/usb-backup/teams/<team>
    sudo rm /etc/nginx/usb-backup/teams.d/<team>.conf /etc/nginx/usb-backup/htpasswd/<team>
    sudo systemctl restart nginx
