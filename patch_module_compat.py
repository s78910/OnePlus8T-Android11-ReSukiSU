import os
import re
import sys

def patch_module_c(kernel_dir):
    module_c = os.path.join(kernel_dir, "kernel", "module.c")
    if not os.path.exists(module_c):
        print(f"[-] module.c not found at {module_c}")
        return False

    with open(module_c, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 1. Patch check_version to bypass symbol CRC verification
    pattern_check_version = r'(static int check_version\(const struct load_info \*info,\s*const char \*symname,\s*struct module \*mod,\s*const s32 \*crc\)\s*\{)'
    replacement_check_version = r'\1\n\t/* Vendor module compatibility bypass */\n\treturn 1;'
    new_content, count1 = re.subn(pattern_check_version, replacement_check_version, content, count=1)
    if count1 == 0:
        print("[-] Failed to patch check_version")
        return False
    print("[+] Successfully patched check_version to return 1")

    # 2. Patch check_modstruct_version to bypass module_layout CRC verification
    pattern_modstruct = r'return check_version\(info,\s*"module_layout",\s*mod,\s*crc\);'
    replacement_modstruct = 'return 1; /* Bypass module_layout CRC */'
    new_content, count2 = re.subn(pattern_modstruct, replacement_modstruct, new_content, count=1)
    if count2 == 0:
        print("[-] Failed to patch check_modstruct_version")
        return False
    print("[+] Successfully patched check_modstruct_version to return 1")

    # 3. Patch same_magic (both definitions) to bypass vermagic mismatch
    pattern_same_magic = r'(static inline int same_magic\(const char \*amagic,\s*const char \*bmagic,\s*bool has_crcs\)\s*\{)'
    replacement_same_magic = r'\1\n\t/* Bypass vermagic mismatch */\n\treturn 1;'
    new_content, count3 = re.subn(pattern_same_magic, replacement_same_magic, new_content)
    if count3 == 0:
        print("[-] Failed to patch same_magic")
        return False
    print(f"[+] Successfully patched same_magic ({count3} occurrences) to return 1")

    # 4. Patch module_sig_check to bypass module signature verification
    pattern_sig_check = r'(static int module_sig_check\(struct load_info \*info,\s*int flags\)\s*\{)'
    replacement_sig_check = r'\1\n\t/* Bypass signature check */\n\treturn 0;'
    new_content, count4 = re.subn(pattern_sig_check, replacement_sig_check, new_content)
    if count4 == 0:
        print("[-] Failed to patch module_sig_check")
        return False
    print(f"[+] Successfully patched module_sig_check ({count4} occurrences) to return 0")

    with open(module_c, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("[+] kernel/module.c successfully patched for 100% vendor module compatibility!")
    return True

if __name__ == "__main__":
    kdir = sys.argv[1] if len(sys.argv) > 1 else "."
    if not patch_module_c(kdir):
        sys.exit(1)
