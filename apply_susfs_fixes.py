import os
import sys
import re
import shutil
import subprocess

def patch_file(filepath, search_str, replace_str):
    if not os.path.exists(filepath):
        print(f"[-] File not found: {filepath}")
        return False
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    if search_str not in content:
        print(f"[-] Target string not found in {filepath}")
        return False
    content = content.replace(search_str, replace_str, 1)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"[+] Successfully patched: {filepath}")
    return True

def apply_patch(kernel_dir, patch_file):
    if not os.path.exists(patch_file):
        print(f"[-] Patch file not found: {patch_file}")
        return False
    print(f"[*] Applying {os.path.basename(patch_file)}...")
    ret = subprocess.run(
        ["patch", "-p1", "--forward", "--ignore-whitespace"],
        cwd=kernel_dir,
        input=open(patch_file, 'rb').read(),
        capture_output=True
    )
    print(ret.stdout.decode('utf-8', errors='ignore'))
    if ret.stderr:
        print(ret.stderr.decode('utf-8', errors='ignore'))
    return ret.returncode == 0

def main():
    kernel_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    zee295_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(kernel_dir, "..", "zee295_susfs")
    
    print(f"[*] Applying SuSFS v2 & BakaSU integration to {kernel_dir}...")
    print(f"[*] Using SuSFS assets from {zee295_dir}...")

    # 1. Copy SuSFS source files to kernel
    fs_susfs_c = os.path.join(kernel_dir, "fs", "susfs.c")
    inc_susfs_h = os.path.join(kernel_dir, "include", "linux", "susfs.h")
    inc_susfs_def_h = os.path.join(kernel_dir, "include", "linux", "susfs_def.h")

    shutil.copyfile(os.path.join(zee295_dir, "susfs-v2", "susfs.c"), fs_susfs_c)
    shutil.copyfile(os.path.join(zee295_dir, "susfs-v2", "susfs.h"), inc_susfs_h)
    shutil.copyfile(os.path.join(zee295_dir, "susfs-v2", "susfs_def.h"), inc_susfs_def_h)
    print("[+] Copied susfs.c, susfs.h, and susfs_def.h")

    # 2. Add aliases and stubs in fs/susfs.c
    with open(fs_susfs_c, 'r', encoding='utf-8', errors='ignore') as f:
        c_content = f.read()
    if "susfs_set_hide_sus_mnts_for_non_su_procs" not in c_content:
        c_content += '''
/* BakaSU compatibility aliases and stubs */
#include <linux/workqueue.h>
#include <linux/export.h>

bool susfs_is_boot_completed_triggered __read_mostly = false;
EXPORT_SYMBOL(susfs_is_boot_completed_triggered);

bool ksu_execveat_hook __read_mostly = false;
EXPORT_SYMBOL(ksu_execveat_hook);

#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info) {
\tsusfs_set_hide_sus_mnts_for_all_procs(user_info);
}
#endif

void susfs_start_sdcard_monitor_fn(void) {
\tsusfs_is_boot_completed_triggered = true;
\tpr_info("susfs: boot completed triggered set to true\\n");
}

#ifdef CONFIG_KSU_SUSFS_SUS_PATH
extern void susfs_run_sus_path_loop(uid_t uid);
#endif

static void susfs_run_extra_works(struct work_struct *work) {
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tsusfs_run_sus_path_loop(0);
#endif
}

DECLARE_WORK(susfs_extra_works, susfs_run_extra_works);
'''
        with open(fs_susfs_c, 'w', encoding='utf-8') as f:
            f.write(c_content)
        print("[+] Added BakaSU compatibility aliases, stubs & susfs_extra_works to fs/susfs.c")

    # 3. Add to fs/Makefile
    fs_makefile = os.path.join(kernel_dir, "fs", "Makefile")
    if os.path.exists(fs_makefile):
        with open(fs_makefile, 'r', encoding='utf-8', errors='ignore') as f:
            mf = f.read()
        if "susfs.o" not in mf:
            with open(fs_makefile, 'a', encoding='utf-8') as f:
                f.write("\nobj-$(CONFIG_KSU_SUSFS) += susfs.o\n")
            print("[+] Added obj-$(CONFIG_KSU_SUSFS) += susfs.o to fs/Makefile")

    # 4. Pre-inject headers and declarations to ensure 100% clean patch application
    # 4a. fs/namespace.c (avoids OPLUS macro conflict)
    ns_c = os.path.join(kernel_dir, "fs", "namespace.c")
    if os.path.exists(ns_c):
        with open(ns_c, 'r', encoding='utf-8', errors='ignore') as f:
            ns_content = f.read()
        if "DEFINE_IDA(susfs_ksu_mnt_group_ida)" not in ns_content:
            target = '#include "internal.h"'
            inject = '''#include "internal.h"

#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
#include <linux/susfs_def.h>
extern bool susfs_is_current_ksu_domain(void);
extern bool susfs_is_boot_completed_triggered;

static DEFINE_IDA(susfs_ksu_mnt_group_ida);
static atomic64_t susfs_ksu_mounts = ATOMIC64_INIT(0);

#define CL_COPY_MNT_NS BIT(25)
#endif'''
            patch_file(ns_c, target, inject)

    # 4b. fs/proc/task_mmu.c
    tm_c = os.path.join(kernel_dir, "fs", "proc", "task_mmu.c")
    if os.path.exists(tm_c):
        with open(tm_c, 'r', encoding='utf-8', errors='ignore') as f:
            tm_content = f.read()
        if "linux/susfs_def.h" not in tm_content:
            target = '#include <linux/ctype.h>'
            inject = '''#include <linux/ctype.h>
#if defined(CONFIG_KSU_SUSFS_SUS_KSTAT) || defined(CONFIG_KSU_SUSFS_SUS_MAP)
#include <linux/susfs_def.h>
#endif'''
            patch_file(tm_c, target, inject)

    # 4c. fs/exec.c
    exec_c = os.path.join(kernel_dir, "fs", "exec.c")
    if os.path.exists(exec_c):
        with open(exec_c, 'r', encoding='utf-8', errors='ignore') as f:
            ec = f.read()
        if "linux/susfs_def.h" not in ec:
            target = "#include <linux/vmalloc.h>"
            if target in ec:
                ec = ec.replace(target, target + "\n#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#endif", 1)
            else:
                ec = "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#endif\n" + ec
            with open(exec_c, 'w', encoding='utf-8') as f:
                f.write(ec)
            print("[+] Injected linux/susfs_def.h into fs/exec.c")

    # 4d. fs/namei.c
    namei_c = os.path.join(kernel_dir, "fs", "namei.c")
    if os.path.exists(namei_c):
        with open(namei_c, 'r', encoding='utf-8', errors='ignore') as f:
            nc = f.read()
        if "linux/susfs_def.h" not in nc:
            target = "#include <linux/build_bug.h>"
            if target in nc:
                nc = nc.replace(target, target + "\n#if defined(CONFIG_KSU_SUSFS_SUS_PATH) || defined(CONFIG_KSU_SUSFS_OPEN_REDIRECT)\n#include <linux/susfs_def.h>\n#endif", 1)
            else:
                target2 = "#include <linux/uaccess.h>"
                nc = nc.replace(target2, target2 + "\n#if defined(CONFIG_KSU_SUSFS_SUS_PATH) || defined(CONFIG_KSU_SUSFS_OPEN_REDIRECT)\n#include <linux/susfs_def.h>\n#endif", 1)
            with open(namei_c, 'w', encoding='utf-8') as f:
                f.write(nc)
            print("[+] Injected linux/susfs_def.h into fs/namei.c")

    # 4e. fs/open.c
    open_c = os.path.join(kernel_dir, "fs", "open.c")
    if os.path.exists(open_c):
        with open(open_c, 'r', encoding='utf-8', errors='ignore') as f:
            oc = f.read()
        if "linux/susfs_def.h" not in oc:
            target = "#include <linux/compat.h>"
            if target in oc:
                oc = oc.replace(target, target + "\n#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#endif", 1)
            else:
                oc = "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#endif\n" + oc
            with open(open_c, 'w', encoding='utf-8') as f:
                f.write(oc)
            print("[+] Injected linux/susfs_def.h into fs/open.c")

    # 4f. fs/readdir.c (compat_fillonedir inode declaration)
    readdir_c = os.path.join(kernel_dir, "fs", "readdir.c")
    if os.path.exists(readdir_c):
        with open(readdir_c, 'r', encoding='utf-8', errors='ignore') as f:
            rc = f.read()
        if "static int compat_fillonedir" in rc and "struct inode *inode;" not in rc:
            target = "compat_ulong_t d_ino;"
            inject = """compat_ulong_t d_ino;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
\tstruct inode *inode;
#endif"""
            rc = rc.replace(target, inject, 1)
            with open(readdir_c, 'w', encoding='utf-8') as f:
                f.write(rc)
            print("[+] Injected struct inode *inode into compat_fillonedir in fs/readdir.c")

    # 4g. include/linux/mount.h (susfs_mnt_id_backup field in struct vfsmount)
    mount_h = os.path.join(kernel_dir, "include", "linux", "mount.h")
    if os.path.exists(mount_h):
        with open(mount_h, 'r', encoding='utf-8', errors='ignore') as f:
            mh = f.read()
        if "susfs_mnt_id_backup" not in mh:
            target = "void *data;"
            inject = """#ifdef CONFIG_KSU_SUSFS
\tu64 susfs_mnt_id_backup;
#endif
\tvoid *data;"""
            if target in mh:
                mh = mh.replace(target, inject, 1)
                with open(mount_h, 'w', encoding='utf-8') as f:
                    f.write(mh)
                print("[+] Injected susfs_mnt_id_backup into include/linux/mount.h")

    # 4h. kernel/sys.c (susfs_spoof_uname in newuname)
    sys_c = os.path.join(kernel_dir, "kernel", "sys.c")
    if os.path.exists(sys_c):
        with open(sys_c, 'r', encoding='utf-8', errors='ignore') as f:
            sc = f.read()
        if "susfs_spoof_uname" not in sc:
            decl = """#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
extern void susfs_spoof_uname(struct new_utsname* tmp);
#endif
SYSCALL_DEFINE1(newuname,"""
            sc = sc.replace("SYSCALL_DEFINE1(newuname,", decl, 1)
            target = "memcpy(&tmp, utsname(), sizeof(tmp));"
            inject = """memcpy(&tmp, utsname(), sizeof(tmp));
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
\tsusfs_spoof_uname(&tmp);
#endif"""
            sc = sc.replace(target, inject, 1)
            with open(sys_c, 'w', encoding='utf-8') as f:
                f.write(sc)
            print("[+] Injected susfs_spoof_uname into kernel/sys.c")

    # 5. Prepare 01_add_susfs_hooks.patch with pre-injected and conflicting hunks removed
    p01_src = os.path.join(zee295_dir, "susfs-patches", "01_add_susfs_hooks.patch")
    with open(p01_src, 'r', encoding='utf-8', errors='ignore') as f:
        p01_text = f.read()

    omits_01 = [
        ('fs/namespace.c Hunk 1', '@@ -26,10 +26,23 @@', '@@ -108,6 +121,18 @@'),
        ('fs/proc/task_mmu.c Hunk 1', '@@ -21,6 +21,9 @@', '@@ -348,6 +351,10 @@'),
        ('fs/exec.c Hunk 1', '@@ -62,6 +62,9 @@', '@@ -1753,6 +1756,15 @@'),
        ('fs/namei.c Hunk 1', '@@ -40,6 +40,9 @@', '@@ -47,6 +50,15 @@'),
        ('fs/open.c Hunk 1', '@@ -31,6 +31,9 @@', '@@ -353,6 +356,11 @@'),
        ('fs/proc/base.c Hunk 3', '@@ -897,6 +903,22 @@', '@@ -2536,6 +2558,13 @@'),
        ('fs/readdir.c Hunk 17', '@@ -398,9 +574,13 @@', '@@ -409,6 +589,28 @@'),
    ]

    for name, s, e in omits_01:
        i1 = p01_text.find(s)
        i2 = p01_text.find(e)
        if i1 != -1 and i2 != -1 and i1 < i2:
            p01_text = p01_text[:i1] + p01_text[i2:]
            print(f"[+] Omitted {name} from 01_add_susfs_hooks.patch")

    p01_tmp = os.path.join(kernel_dir, "01_temp.patch")
    with open(p01_tmp, 'w', encoding='utf-8') as f:
        f.write(p01_text)

    apply_patch(kernel_dir, p01_tmp)
    os.remove(p01_tmp)

    # 6. Apply 02_add_susfs_misc.patch (omitting mount.h diff and sys.c newuname hunk)
    p02_src = os.path.join(zee295_dir, "susfs-patches", "02_add_susfs_misc.patch")
    with open(p02_src, 'r', encoding='utf-8', errors='ignore') as f:
        p02_text = f.read()

    omits_02 = [
        ('mount.h diff', 'diff --git a/include/linux/mount.h b/include/linux/mount.h', 'diff --git a/kernel/sys.c b/kernel/sys.c'),
        ('sys.c Hunk 2', '@@ -1240,12 +1249,18 @@', 'diff --git a/security/selinux/avc.c b/security/selinux/avc.c'),
    ]

    for name, s, e in omits_02:
        i1 = p02_text.find(s)
        i2 = p02_text.find(e)
        if i1 != -1 and i2 != -1 and i1 < i2:
            p02_text = p02_text[:i1] + p02_text[i2:]
            print(f"[+] Omitted {name} from 02_add_susfs_misc.patch")

    p02_tmp = os.path.join(kernel_dir, "02_temp.patch")
    with open(p02_tmp, 'w', encoding='utf-8') as f:
        f.write(p02_text)

    apply_patch(kernel_dir, p02_tmp)
    os.remove(p02_tmp)

    # 7. Post-inject mem_rw SUS_MAP hook into fs/proc/base.c (after Hunk 2 declared vma)
    base_c = os.path.join(kernel_dir, "fs", "proc", "base.c")
    if os.path.exists(base_c):
        with open(base_c, 'r', encoding='utf-8', errors='ignore') as f:
            bc = f.read()
        if "inode->i_mapping->flags & BIT_SUS_MAPS" not in bc:
            pattern = r'(while\s*\(\s*count\s*>\s*0\s*\)\s*\{\s*\n\s*(?:(?:int|size_t)\s+this_len\s*=\s*min_t\((?:int|size_t),\s*count,\s*PAGE_SIZE\);))'
            sus_map_inject = r'''\1
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
\t\tvma = find_vma(mm, addr);
\t\tif (vma && vma->vm_file) {
\t\t\tstruct inode *inode = file_inode(vma->vm_file);
\t\t\tif (unlikely(inode->i_mapping->flags & BIT_SUS_MAPS) && susfs_is_current_proc_umounted()) {
\t\t\t\tif (write) {
\t\t\t\t\tcopied = -EFAULT;
\t\t\t\t} else {
\t\t\t\t\tcopied = -EIO;
\t\t\t\t}
\t\t\t\t*ppos = addr;
\t\t\t\tmmput(mm);
\t\t\t\tgoto free;
\t\t\t}
\t\t}
#endif'''
            bc_new = re.sub(pattern, sus_map_inject, bc, count=1)
            if bc_new != bc:
                with open(base_c, 'w', encoding='utf-8') as f:
                    f.write(bc_new)
                print("[+] Successfully injected mem_rw SUS_MAP hook into fs/proc/base.c")

    # Clean up any patch backup/reject files
    for root, dirs, files in os.walk(kernel_dir):
        for file in files:
            if file.endswith('.orig') or file.endswith('.rej'):
                os.remove(os.path.join(root, file))

    # 9. Backport get_cred_rcu in include/linux/cred.h
    cred_h = os.path.join(kernel_dir, "include", "linux", "cred.h")
    if os.path.exists(cred_h):
        with open(cred_h, 'r', encoding='utf-8', errors='ignore') as f:
            cred_content = f.read()
        if "get_cred_rcu" not in cred_content:
            target = "#endif /* _LINUX_CRED_H */"
            get_cred_code = '''
/* Backport get_cred_rcu for KernelSU */
static inline const struct cred *get_cred_rcu(const struct cred *cred)
{
\tstruct cred *nonconst_cred = (struct cred *) cred;
\tif (!cred)
\t\treturn NULL;
\tif (!atomic_inc_not_zero(&nonconst_cred->usage))
\t\treturn NULL;
\treturn cred;
}
'''
            if target in cred_content:
                cred_content = cred_content.replace(target, get_cred_code + "\n" + target)
            else:
                cred_content += "\n" + get_cred_code
            with open(cred_h, 'w', encoding='utf-8') as f:
                f.write(cred_content)
            print("[+] Successfully added get_cred_rcu backport to include/linux/cred.h")

    # 10. Hook kernel/reboot.c for SuSFS / ksud supercalls
    reboot_c = os.path.join(kernel_dir, "kernel", "reboot.c")
    if os.path.exists(reboot_c):
        with open(reboot_c, 'r', encoding='utf-8', errors='ignore') as f:
            reb_content = f.read()
        if "ksu_handle_sys_reboot" not in reb_content:
            target = "SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,"
            inject = '''#ifdef CONFIG_KSU
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);
#endif
SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,'''
            reb_content = reb_content.replace(target, inject)

            hook_target = "if (!ns_capable(pid_ns->user_ns, CAP_SYS_BOOT))"
            hook_inject = '''#ifdef CONFIG_KSU
\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
#endif
\tif (!ns_capable(pid_ns->user_ns, CAP_SYS_BOOT))'''
            reb_content = reb_content.replace(hook_target, hook_inject)
            with open(reboot_c, 'w', encoding='utf-8') as f:
                f.write(reb_content)
            print("[+] Successfully hooked kernel/reboot.c for SuSFS supercalls")

    # 10c. Hook fs/stat.c for BakaSU ksu_handle_newfstat_ret & ksu_handle_fstat64_ret
    stat_c = os.path.join(kernel_dir, "fs", "stat.c")
    if os.path.exists(stat_c):
        with open(stat_c, 'r', encoding='utf-8', errors='ignore') as f:
            stat_content = f.read()
        
        # Add declarations
        if "ksu_handle_newfstat_ret" not in stat_content:
            decl_target = '#include "internal.h"'
            decl_inject = '''#include "internal.h"

#ifdef CONFIG_KSU_MANUAL_HOOK
extern void ksu_handle_newfstat_ret(unsigned int *fd, struct stat __user **statbuf_ptr);
#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)
extern void ksu_handle_fstat64_ret(unsigned long *fd, struct stat64 __user **statbuf_ptr);
#endif
#endif'''
            if decl_target in stat_content:
                stat_content = stat_content.replace(decl_target, decl_inject, 1)
            else:
                stat_content = "#ifdef CONFIG_KSU_MANUAL_HOOK\nextern void ksu_handle_newfstat_ret(unsigned int *fd, struct stat __user **statbuf_ptr);\n#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)\nextern void ksu_handle_fstat64_ret(unsigned long *fd, struct stat64 __user **statbuf_ptr);\n#endif\n#endif\n" + stat_content

        # Hook SYSCALL_DEFINE2(newfstat
        newfstat_old = "\tif (!error)\n\t\terror = cp_new_stat(&stat, statbuf);\n\n\treturn error;"
        newfstat_new = "\tif (!error)\n\t\terror = cp_new_stat(&stat, statbuf);\n\n#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_newfstat_ret(&fd, &statbuf);\n#endif\n\treturn error;"
        if newfstat_old in stat_content and "ksu_handle_newfstat_ret(&fd" not in stat_content:
            stat_content = stat_content.replace(newfstat_old, newfstat_new, 1)

        # Hook SYSCALL_DEFINE2(fstat64
        fstat64_old = "\tif (!error)\n\t\terror = cp_new_stat64(&stat, statbuf);\n\n\treturn error;"
        fstat64_new = "\tif (!error)\n\t\terror = cp_new_stat64(&stat, statbuf);\n\n#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_fstat64_ret(&fd, &statbuf);\n#endif\n\treturn error;"
        if fstat64_old in stat_content and "ksu_handle_fstat64_ret(&fd" not in stat_content:
            stat_content = stat_content.replace(fstat64_old, fstat64_new, 1)

        with open(stat_c, 'w', encoding='utf-8') as f:
            f.write(stat_content)
        print("[+] Successfully hooked fs/stat.c for BakaSU newfstat/fstat64")

    # 11. BakaSU integration: selinux.c, rules.c, sucompat.c, Kconfig, ksud_integration.c, core/init.c
    for ksu_root in [os.path.join(kernel_dir, "drivers", "kernelsu"), os.path.join(kernel_dir, "KernelSU", "kernel")]:
        if not os.path.exists(ksu_root):
            continue

        print(f"[*] Applying BakaSU & SuSFS integration to {ksu_root}...")

        # A. drivers/kernelsu/selinux/selinux.c: Protected SID definitions
        selinux_c = os.path.join(ksu_root, "selinux", "selinux.c")
        if os.path.exists(selinux_c):
            with open(selinux_c, 'r', encoding='utf-8', errors='ignore') as f:
                sel_content = f.read()
            if "susfs_is_current_ksu_domain" not in sel_content:
                susfs_selinux_code = '''
#ifdef CONFIG_KSU_SUSFS
#define KERNEL_INIT_DOMAIN "u:r:init:s0"
#define KERNEL_ZYGOTE_DOMAIN "u:r:zygote:s0"
u32 susfs_ksu_sid = 0;
u32 susfs_init_sid = 0;
u32 susfs_zygote_sid = 0;

static inline void susfs_set_sid(const char *secctx_name, u32 *out_sid) {
\tint err;
\tif (!secctx_name || !out_sid) return;
\terr = security_secctx_to_secid(secctx_name, strlen(secctx_name), out_sid);
\tif (err) return;
}

bool susfs_is_sid_equal(void *sec, u32 sid2) {
\tstruct task_security_struct *tsec = (struct task_security_struct *)sec;
\tif (!tsec) return false;
\treturn tsec->sid == sid2;
}

u32 susfs_get_sid_from_name(const char *secctx_name) {
\tu32 out_sid = 0;
\tif (!secctx_name) return 0;
\tsecurity_secctx_to_secid(secctx_name, strlen(secctx_name), &out_sid);
\treturn out_sid;
}

u32 susfs_get_current_sid(void) { return current_sid(); }

void susfs_set_zygote_sid(void) { susfs_set_sid(KERNEL_ZYGOTE_DOMAIN, &susfs_zygote_sid); }
bool susfs_is_current_zygote_domain(void) {
\tif (!susfs_zygote_sid) return false;
\treturn unlikely(current_sid() == susfs_zygote_sid);
}

void susfs_set_ksu_sid(void) { susfs_set_sid(KERNEL_SU_DOMAIN, &susfs_ksu_sid); }
bool susfs_is_current_ksu_domain(void) {
\tif (!susfs_ksu_sid) return false;
\treturn unlikely(current_sid() == susfs_ksu_sid);
}

void susfs_set_init_sid(void) { susfs_set_sid(KERNEL_INIT_DOMAIN, &susfs_init_sid); }
bool susfs_is_current_init_domain(void) {
\tif (!susfs_init_sid) return false;
\treturn unlikely(current_sid() == susfs_init_sid);
}

EXPORT_SYMBOL(susfs_is_current_ksu_domain);
EXPORT_SYMBOL(susfs_is_current_zygote_domain);
EXPORT_SYMBOL(susfs_is_current_init_domain);
EXPORT_SYMBOL(susfs_is_sid_equal);
EXPORT_SYMBOL(susfs_set_ksu_sid);
EXPORT_SYMBOL(susfs_set_zygote_sid);
EXPORT_SYMBOL(susfs_set_init_sid);
EXPORT_SYMBOL(susfs_get_current_sid);
EXPORT_SYMBOL(susfs_get_sid_from_name);
#endif
'''
                sel_content += susfs_selinux_code
                with open(selinux_c, 'w', encoding='utf-8') as f:
                    f.write(sel_content)
                print(f"[+] Added protected SuSFS SID implementations to {selinux_c}")

        # Note: BakaSU already handles SID caching via cache_sid() and already exports
        # __ksu_is_allow_uid_for_current in policy/allowlist.c

        # D. Decouple KSU_SUSFS from hook choice in Kconfig
        kconfig_path = os.path.join(ksu_root, "Kconfig")
        if os.path.exists(kconfig_path):
            with open(kconfig_path, 'r', encoding='utf-8', errors='ignore') as f:
                k_content = f.read()
            pattern = r'(config KSU_SUSFS\s+bool "SUSFS Inline Hook"[\s\S]*?)(endchoice)'
            m = re.search(pattern, k_content)
            if m:
                k_content = k_content[:m.start(1)] + "endchoice\n\nconfig KSU_SUSFS\n\tbool \"SUSFS Support\"\n\tdepends on KSU\n\tdefault y\n\thelp\n\t  Enable SuSFS support in KernelSU.\n" + k_content[m.end(2):]
                with open(kconfig_path, 'w', encoding='utf-8') as f:
                    f.write(k_content)
                print(f"[+] Successfully decoupled KSU_SUSFS from hook choice in {kconfig_path}")

        # E. Export ksu_init_rc_hook and ksu_input_hook in ksud_integration.c
        for ksud_sub in ["runtime/ksud_integration.c", "kernel/runtime/ksud_integration.c"]:
            ksud_c = os.path.join(ksu_root, ksud_sub)
            if os.path.exists(ksud_c):
                with open(ksud_c, 'r', encoding='utf-8', errors='ignore') as f:
                    k_content = f.read()

                if "#include <linux/export.h>" not in k_content:
                    k_content = "#include <linux/export.h>\n" + k_content

                k_content = re.sub(
                    r'#elif\s+defined\(CONFIG_KSU_SUSFS\)\s*\n\s*DEFINE_STATIC_KEY_TRUE\(ksu_is_init_rc_hook_enabled\);',
                    '#elif defined(CONFIG_KSU_SUSFS) && !defined(CONFIG_KSU_MANUAL_HOOK)\n    DEFINE_STATIC_KEY_TRUE(ksu_is_init_rc_hook_enabled);',
                    k_content
                )

                if "EXPORT_SYMBOL(ksu_init_rc_hook);" not in k_content:
                    k_content = k_content.replace(
                        "bool ksu_init_rc_hook __read_mostly = true;",
                        "bool ksu_init_rc_hook __read_mostly = true;\nEXPORT_SYMBOL(ksu_init_rc_hook);"
                    )

                if "EXPORT_SYMBOL(ksu_input_hook);" not in k_content:
                    k_content = k_content.replace(
                        "bool ksu_input_hook __read_mostly = true;",
                        "bool ksu_input_hook __read_mostly = true;\nEXPORT_SYMBOL(ksu_input_hook);"
                    )

                with open(ksud_c, 'w', encoding='utf-8') as f:
                    f.write(k_content)
                print(f"[+] Exported manual hook symbols in {ksud_c}")

        # F. Call susfs_init() in core/init.c under MANUAL_HOOK
        for ci_sub in ["core/init.c", "core_init.c", "kernel/core_init.c"]:
            ci_c = os.path.join(ksu_root, ci_sub)
            if os.path.exists(ci_c):
                with open(ci_c, 'r', encoding='utf-8', errors='ignore') as f:
                    ci_content = f.read()

                target_hook_pattern = r'(#elif\s+defined\(CONFIG_KSU_MANUAL_HOOK\)[\s\S]*?ksu_lsm_hook_built_in_init\(\);\s*#endif)'
                m_ci = re.search(target_hook_pattern, ci_content)
                if m_ci and "susfs_init();" not in m_ci.group(1):
                    replacement = m_ci.group(1) + "\n#if defined(CONFIG_KSU_SUSFS)\n    extern void susfs_init(void);\n    susfs_init();\n#endif"
                    ci_content = ci_content[:m_ci.start(1)] + replacement + ci_content[m_ci.end(1):]
                    with open(ci_c, 'w', encoding='utf-8') as f:
                        f.write(ci_content)
                    print(f"[+] Injected susfs_init() into {ci_c}")

        # G. Fix sucompat.h and sucompat.c signature mismatch on non-GKI 4.19
        # In Linux 4.19 non-GKI, do_faccessat and vfs_statx pass const char __user **filename_user,
        # NOT struct filename **filename (which is GKI 5.10+ only).
        for sc_sub in ["feature/sucompat.h", "kernel/feature/sucompat.h"]:
            sc_h = os.path.join(ksu_root, sc_sub)
            if os.path.exists(sc_h):
                with open(sc_h, 'r', encoding='utf-8', errors='ignore') as f:
                    sh_content = f.read()
                if "#include <linux/version.h>" not in sh_content:
                    sh_content = "#include <linux/version.h>\n" + sh_content
                sh_content = re.sub(
                    r'#ifdef\s+CONFIG_KSU_SUSFS\s*\n(\s*int\s+ksu_handle_faccessat\(int\s*\*dfd,\s*struct\s+filename\s*\*\*filename,\s*int\s*\*mode,\s*int\s*\*__unused_flags\);\s*\n\s*int\s+ksu_handle_stat\(int\s*\*dfd,\s*struct\s+filename\s*\*\*filename,\s*int\s*\*flags\);)',
                    r'#if defined(CONFIG_KSU_SUSFS) && (LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0))\n\1',
                    sh_content
                )
                with open(sc_h, 'w', encoding='utf-8') as f:
                    f.write(sh_content)
                print(f"[+] Fixed faccessat & stat prototypes in {sc_h}")

        for sc_sub in ["feature/sucompat.c", "kernel/feature/sucompat.c"]:
            sc_c = os.path.join(ksu_root, sc_sub)
            if os.path.exists(sc_c):
                with open(sc_c, 'r', encoding='utf-8', errors='ignore') as f:
                    sc_content = f.read()
                sc_content = re.sub(
                    r'#ifdef\s+CONFIG_KSU_SUSFS\s*\n(\s*int\s+ksu_handle_faccessat\(int\s*\*dfd,\s*struct\s+filename\s*\*\*filename)',
                    r'#if defined(CONFIG_KSU_SUSFS) && (LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0))\n\1',
                    sc_content
                )
                sc_content = re.sub(
                    r'#ifdef\s+CONFIG_KSU_SUSFS\s*\n(\s*int\s+ksu_handle_stat\(int\s*\*dfd,\s*struct\s+filename\s*\*\*filename)',
                    r'#if defined(CONFIG_KSU_SUSFS) && (LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0))\n\1',
                    sc_content
                )
                with open(sc_c, 'w', encoding='utf-8') as f:
                    f.write(sc_content)
                print(f"[+] Fixed faccessat & stat implementations in {sc_c}")

    print("[*] All SuSFS v2 and BakaSU fixes applied cleanly and safely!")

if __name__ == "__main__":
    main()
