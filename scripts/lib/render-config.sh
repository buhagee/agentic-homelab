#!/usr/bin/env bash
# Renders Traefik file-provider templates that contain secrets or host values.
# Source this file; it does not execute.

render_traefik_dynamic() {
  local platform_dir="${1:?platform directory required}"
  local dir="${platform_dir}/infrastructure/traefik/config/dynamic"
  local key="${CROWDSEC_LAPI_KEY:-}"
  local domain="${QACEY_DOMAIN:-}"
  local template
  local rendered
  local tmp

  if [[ ! "$key" =~ ^[A-Fa-f0-9]{16,}$ ]]; then
    echo "CROWDSEC_LAPI_KEY missing or not hex; refusing to render ${dir}" >&2
    return 1
  fi
  if [[ -z "$domain" ]]; then
    echo "QACEY_DOMAIN missing; refusing to render ${dir}" >&2
    return 1
  fi
  if [[ ! -f "${dir}/middlewares.yml.tmpl" ]]; then
    echo "Missing required template: ${dir}/middlewares.yml.tmpl" >&2
    return 1
  fi

  for template in "${dir}"/*.yml.tmpl; do
    [[ -e "$template" ]] || continue
    rendered="${template%.tmpl}"
    tmp="$(mktemp "${dir}/.render.XXXXXX")" || return 1
    if ! sed \
      -e "s|__CROWDSEC_LAPI_KEY__|${key}|g" \
      -e "s|__QACEY_DOMAIN__|${domain}|g" \
      "$template" > "$tmp"; then
      rm -f "$tmp"
      return 1
    fi
    chmod 600 "$tmp" || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$rendered" || { rm -f "$tmp"; return 1; }
  done
}
