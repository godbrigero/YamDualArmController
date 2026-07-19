#!/usr/bin/env bash

set -Eeuo pipefail

readonly REPOSITORY_URL="${YAM_INITIALIZER_REPOSITORY_URL:-https://github.com/godbrigero/YamDualArmController.git}"
readonly WINNOW_REPOSITORY_URL="${YAM_INITIALIZER_WINNOW_URL:-https://github.com/AdamEXu/winnow.git}"
readonly PROJECT_DIRECTORY="$PWD"

temporary_directory=""
uv_executable=""

require_uv() {
    if ! uv_executable="$(command -v uv)"; then
        printf 'UV is required but is not installed. Aborting before project setup.\n' >&2
        printf 'Install UV from: https://docs.astral.sh/uv/getting-started/installation/\n' >&2
        return 1
    fi
}

remove_temporary_directory() {
    if [[ -n "$temporary_directory" && -d "$temporary_directory" ]]; then
        rm -rf -- "$temporary_directory"
    fi

    temporary_directory=""
}

cleanup() {
    local exit_status=$?

    trap - EXIT

    remove_temporary_directory

    exit "$exit_status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

sync_managed_file() {
    local source_file=$1
    local target_file=$2

    if [[ -d "$target_file" ]]; then
        printf 'Cannot update managed file because the target is a directory: %s\n' "$target_file" >&2
        return 1
    fi

    if [[ -f "$target_file" ]] && cmp -s "$source_file" "$target_file"; then
        printf 'Already up to date: %s\n' "$target_file"
        return
    fi

    if [[ -e "$target_file" ]]; then
        printf 'Updating: %s\n' "$target_file"
    else
        printf 'Installing: %s\n' "$target_file"
    fi

    mkdir -p "$(dirname "$target_file")"
    cp -p "$source_file" "$target_file"
}

sync_managed_directory() {
    local source_directory=$1
    local target_directory=$2

    if [[ -e "$target_directory" && ! -d "$target_directory" ]]; then
        printf 'Cannot update managed directory because the target is not a directory: %s\n' "$target_directory" >&2
        return 1
    fi

    if [[ -d "$target_directory" ]] && diff -qr "$source_directory" "$target_directory" >/dev/null; then
        printf 'Already up to date: %s/\n' "$target_directory"
        return
    fi

    if [[ -d "$target_directory" ]]; then
        printf 'Updating: %s/\n' "$target_directory"
        rm -rf -- "$target_directory"
    else
        printf 'Installing: %s/\n' "$target_directory"
    fi

    mkdir -p "$target_directory"
    cp -R "$source_directory/." "$target_directory/"
}

# Episode triage lives in a separate repository with its own pinned environment,
# so it is cloned beside the project rather than vendored into it. Curation is
# optional — a clone failure must not take the whole setup down with it.
install_winnow() {
    local project_directory=$1
    local target_directory="$project_directory/third_party/winnow"
    local staging_directory

    # -e, not -d: a submodule or worktree checkout has a .git *file*, and this
    # function must never delete a checkout it did not create.
    if [[ -e "$target_directory/.git" ]]; then
        printf 'Updating: %s/\n' "$target_directory"
        git -C "$target_directory" pull --ff-only --quiet || \
            printf 'Could not update winnow; keeping the existing checkout.\n' >&2
        return 0
    fi

    # an empty directory is what an uninitialized submodule entry or an
    # interrupted clone leaves behind; that should not lock installation out
    if [[ -e "$target_directory" ]] && [[ -n "$(ls -A "$target_directory" 2>/dev/null)" ]]; then
        printf 'Not touching existing %s: it is not a git checkout, so winnow was\n' \
            "$target_directory" >&2
        printf 'not installed. Move it aside if you want the initializer to manage it.\n' >&2
        return 0
    fi

    # Clone to a sibling and move it into place, so a failed clone only ever
    # removes what this function just created. Every step is guarded: curation
    # is optional and must never take the rest of the setup down with it, which
    # an unguarded failure would do under `set -e`.
    printf 'Installing: %s/\n' "$target_directory"
    mkdir -p "$(dirname "$target_directory")" || { winnow_unavailable; return 0; }
    staging_directory="$(mktemp -d "$(dirname "$target_directory")/.winnow-clone.XXXXXX")" || {
        winnow_unavailable
        return 0
    }

    # git clone accepts an existing empty directory, so mktemp's is reused as-is
    if git clone --depth 1 --quiet "$WINNOW_REPOSITORY_URL" "$staging_directory"; then
        rmdir "$target_directory" 2>/dev/null || true
        if mv -- "$staging_directory" "$target_directory"; then
            return 0
        fi
    fi

    rm -rf -- "$staging_directory" 2>/dev/null || true
    winnow_unavailable
    return 0
}

winnow_unavailable() {
    printf 'Could not install winnow from %s. Episode curation will be unavailable\n' \
        "$WINNOW_REPOSITORY_URL" >&2
    printf 'until you clone it into third_party/winnow yourself.\n' >&2
}

run_project_initialization() {
    local repository_directory=$1
    local project_directory=$2
    local source_calibration_script="$repository_directory/scripts/calibrate.py"
    local source_bridge_directory="$repository_directory/leader_yam_bridge"
    local source_teleoperation_directory="$repository_directory/teleoperation"
    local source_skill_directory="$repository_directory/skills/connect-yam-leader"
    local target_scripts_directory="$project_directory/scripts"
    local target_bridge_directory="$project_directory/leader_yam_bridge"
    local target_teleoperation_directory="$project_directory/teleoperation"

    if [[ ! -f "$source_calibration_script" ]]; then
        printf 'Missing required file in cloned repository: %s\n' "$source_calibration_script" >&2
        return 1
    fi

    if [[ ! -d "$source_bridge_directory" ]]; then
        printf 'Missing required directory in cloned repository: %s\n' "$source_bridge_directory" >&2
        return 1
    fi

    if [[ ! -f "$source_teleoperation_directory/__main__.py" ]]; then
        printf 'Missing required file in cloned repository: %s\n' "$source_teleoperation_directory/__main__.py" >&2
        return 1
    fi

    if [[ ! -f "$source_skill_directory/SKILL.md" ]]; then
        printf 'Missing required setup skill in cloned repository: %s\n' "$source_skill_directory" >&2
        return 1
    fi

    if [[ ! -f "$repository_directory/curation/__main__.py" ]]; then
        printf 'Missing required directory in cloned repository: %s\n' \
            "$repository_directory/curation" >&2
        return 1
    fi

    sync_managed_file "$source_calibration_script" "$target_scripts_directory/calibrate.py"
    sync_managed_directory "$source_bridge_directory" "$target_bridge_directory"
    sync_managed_directory "$source_teleoperation_directory" "$target_teleoperation_directory"
    sync_managed_directory "$repository_directory/curation" "$project_directory/curation"
    install_winnow "$project_directory"
    sync_managed_directory "$source_skill_directory" "$project_directory/.agents/skills/connect-yam-leader"
    sync_managed_directory "$source_skill_directory" "$project_directory/.claude/skills/connect-yam-leader"

    if [[ -d "$project_directory/outputs" ]]; then
        printf 'Preserving existing calibration output directory: %s/\n' "$project_directory/outputs"
    else
        printf 'Creating empty calibration output directory: %s/\n' "$project_directory/outputs"
        mkdir -p "$project_directory/outputs"
    fi
}

ensure_ruckig_build_constraint() {
    local project_directory=$1
    local pyproject_file="$project_directory/pyproject.toml"
    local updated_pyproject_file

    if grep -Eq '^[[:space:]]*build-constraint-dependencies[[:space:]]*=' "$pyproject_file"; then
        return
    fi

    updated_pyproject_file="$(mktemp "$project_directory/.yam-pyproject.XXXXXX")"
    cp -p "$pyproject_file" "$updated_pyproject_file"

    if ! awk '
        BEGIN { added = 0 }
        /^[[:space:]]*\[tool\.uv\][[:space:]]*(#.*)?$/ && !added {
            print
            print "build-constraint-dependencies = [\"scikit-build-core<0.10\"]"
            added = 1
            next
        }
        { print }
        END {
            if (!added) {
                print ""
                print "[tool.uv]"
                print "build-constraint-dependencies = [\"scikit-build-core<0.10\"]"
            }
        }
    ' "$pyproject_file" >"$updated_pyproject_file"; then
        rm -f -- "$updated_pyproject_file"
        return 1
    fi

    mv -- "$updated_pyproject_file" "$pyproject_file"
}

configure_uv_project() {
    local project_directory=$1
    local build_constraints_file="$temporary_directory/ruckig-build-constraints.txt"

    printf 'Configuring UV project dependencies...\n'

    if [[ ! -f "$project_directory/pyproject.toml" ]]; then
        "$uv_executable" init \
            --bare \
            --name yam-teleoperation \
            --python '>=3.12,<3.13' \
            --no-workspace \
            "$project_directory"
    fi

    # Ruckig 0.15.3 still uses the pre-0.10 scikit-build-core setting name
    # `cmake.targets`. Newer build backends reject it before compilation.
    ensure_ruckig_build_constraint "$project_directory"
    printf 'scikit-build-core<0.10\n' >"$build_constraints_file"

    (
        cd "$project_directory"
        UV_BUILD_CONSTRAINT="$build_constraints_file" "$uv_executable" add \
            --no-workspace \
            --upgrade-package numpy \
            --upgrade-package feetech-servo-sdk \
            --upgrade-package i2rt \
            numpy \
            feetech-servo-sdk \
            'i2rt @ git+https://github.com/i2rt-robotics/i2rt.git'
    )
}

show_calibration_prompt() {
    local message='Project setup is complete. Ask Codex for $connect-yam-leader or Claude Code for /connect-yam-leader. First run "uv run scripts/calibrate.py", then start teleoperation with "uv run -m teleoperation".'

    if [[ "${YAM_INITIALIZER_SKIP_PROMPT:-0}" == "1" ]]; then
        printf '\n%s\n' "$message"
        return
    fi

    if command -v whiptail >/dev/null 2>&1; then
        whiptail --title 'YAM Project Setup' --msgbox "$message" 12 72
    elif command -v dialog >/dev/null 2>&1; then
        dialog --title 'YAM Project Setup' --msgbox "$message" 12 72
    elif [[ -t 0 && -t 1 ]]; then
        printf '\nYAM Project Setup\n\n%s\n\n' "$message"
        printf '                \033[7m  OK  \033[0m\n'
        read -r -p 'Press Enter to select OK... ' _
    else
        printf '\n%s\n' "$message"
    fi
}

main() {
    require_uv

    temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/yam-project-initializer.XXXXXX")"
    local cloned_repository_directory="$temporary_directory/YamDualArmController"

    printf 'Cloning YamDualArmController...\n'
    git clone --depth 1 "$REPOSITORY_URL" "$cloned_repository_directory"

    run_project_initialization "$cloned_repository_directory" "$PROJECT_DIRECTORY"
    configure_uv_project "$PROJECT_DIRECTORY"
    remove_temporary_directory

    printf 'Project initialization complete.\n'
    show_calibration_prompt
}

if [[ -z "${BASH_SOURCE[0]-}" || "${BASH_SOURCE[0]-}" == "$0" ]]; then
    main "$@"
fi
