#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugin_dir="$repo_root/dbeaver-plugin"
dbeaver_app="${DBEAVER_APP:-/Applications/DBeaver.app}"
eclipse_dir="$dbeaver_app/Contents/Eclipse"
plugins_dir="$eclipse_dir/plugins"
bundles_info="$eclipse_dir/configuration/org.eclipse.equinox.simpleconfigurator/bundles.info"
build_dir="$plugin_dir/target/dbeaver-install"
classes_dir="$build_dir/classes"
artifact_name="com.plaindb.dbeaver_0.1.0.qualifier.jar"

if [[ -z "${JAVA_HOME:-}" && -d "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home" ]]; then
  export JAVA_HOME="/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
elif [[ -z "${JAVA_HOME:-}" && -d "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home" ]]; then
  export JAVA_HOME="/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
fi

if [[ -z "${JAVA_HOME:-}" ]]; then
  echo "JAVA_HOME is not set and openjdk@17 was not found at the Homebrew default path." >&2
  exit 1
fi

export PATH="$JAVA_HOME/bin:$PATH"

if [[ ! -d "$dbeaver_app" ]]; then
  echo "DBeaver app not found at: $dbeaver_app" >&2
  echo "Set DBEAVER_APP to your local DBeaver.app path." >&2
  exit 1
fi

mkdir -p "$classes_dir"

classpath="$(find "$plugins_dir" -name '*.jar' -print | paste -sd ':' -)"

"$JAVA_HOME/bin/javac" \
  -source 21 \
  -target 21 \
  -encoding UTF-8 \
  -cp "$classpath" \
  -d "$classes_dir" \
  $(find "$plugin_dir/src/main/java" -name '*.java' -print)

mkdir -p "$classes_dir/META-INF"
cp "$plugin_dir/META-INF/MANIFEST.MF" "$classes_dir/META-INF/MANIFEST.MF"
cp "$plugin_dir/plugin.xml" "$classes_dir/plugin.xml"

"$JAVA_HOME/bin/jar" cfm "$build_dir/$artifact_name" "$classes_dir/META-INF/MANIFEST.MF" -C "$classes_dir" .

rm -f "$plugins_dir/$artifact_name"
rm -f "$eclipse_dir/dropins/plaindb/plugins/$artifact_name"
cp "$build_dir/$artifact_name" "$plugins_dir/$artifact_name"

# Ensure Equinox loads the plugin from the real plugins directory path.
if [[ -f "$bundles_info" ]]; then
  entry="com.plaindb.dbeaver,0.1.0.qualifier,plugins/$artifact_name,4,false"
  if grep -q '^com\.plaindb\.dbeaver,' "$bundles_info"; then
    awk -v replacement="$entry" '
      BEGIN { replaced = 0 }
      {
        if ($0 ~ /^com\.plaindb\.dbeaver,/) {
          if (!replaced) {
            print replacement;
            replaced = 1;
          }
        } else {
          print $0;
        }
      }
      END {
        if (!replaced) {
          print replacement;
        }
      }
    ' "$bundles_info" > "$bundles_info.tmp"
    mv "$bundles_info.tmp" "$bundles_info"
  else
    printf '\n%s\n' "$entry" >> "$bundles_info"
  fi
fi

echo "Installed $artifact_name into $plugins_dir"
echo "Restart DBeaver to load the plugin."
