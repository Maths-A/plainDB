#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPDATE_SITE_DIR="$REPO_ROOT/update-site"
FEATURES_DIR="$UPDATE_SITE_DIR/features"
PLUGINS_DIR="$UPDATE_SITE_DIR/plugins"
FEATURE_ID="com.plaindb.dbeaver.feature_1.0.0"
FEATURE_DIR="$FEATURES_DIR/$FEATURE_ID"
SIGN_DIR="$UPDATE_SITE_DIR/.signing"

# Optional signing identity used by local update-site builds.
SIGN_ENABLED="${PLAINDB_SIGN_UPDATE_SITE:-1}"
SIGN_ALIAS="${PLAINDB_SIGN_ALIAS:-plaindb-local}"
SIGN_DNAME="${PLAINDB_SIGN_DNAME:-CN=PlainDB Local, OU=Research, O=UCSC, L=Santa Cruz, ST=CA, C=US}"
SIGN_STOREPASS="${PLAINDB_SIGN_STOREPASS:-plaindb-local-dev}"
SIGN_KEYPASS="${PLAINDB_SIGN_KEYPASS:-plaindb-local-dev}"
SIGN_KEYSTORE="${PLAINDB_SIGN_KEYSTORE:-$SIGN_DIR/plaindb-local-dev.p12}"

# Get OpenJDK 21
JAVA_HOME="/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"

echo "Building PlainDB update site..."
echo "Java: $(which java)"

# Step 1: Copy existing compiled plugin JAR
echo ""
echo "Step 1: Copying compiled plugin JAR..."
EXISTING_JAR="/Applications/DBeaver.app/Contents/Eclipse/plugins/com.plaindb.dbeaver_0.1.0.qualifier.jar"
PLUGIN_JAR="$PLUGINS_DIR/com.plaindb.dbeaver_0.1.0.qualifier.jar"
mkdir -p "$PLUGINS_DIR"

if [ ! -f "$EXISTING_JAR" ]; then
  echo "ERROR: Plugin JAR not found at $EXISTING_JAR"
  echo "Please run 'scripts/run-local-dbeaver.sh' first to build and install the plugin"
  exit 1
fi

cp "$EXISTING_JAR" "$PLUGIN_JAR"
echo "✓ Plugin JAR copied: $PLUGIN_JAR"

# Step 2: Create feature JAR
echo ""
echo "Step 2: Creating feature JAR..."
FEATURE_JAR="$FEATURES_DIR/$FEATURE_ID.jar"

cd "$FEATURE_DIR"
jar cf "$FEATURE_JAR" \
  feature.xml \
  build.properties \
  2>&1 | head -20

echo "✓ Feature JAR created: $FEATURE_JAR"

# Step 2.5: Sign plugin and feature artifacts to avoid unsigned/unknown prompt text.
if [[ "$SIGN_ENABLED" != "0" ]]; then
  echo ""
  echo "Step 2.5: Signing plugin and feature JARs..."
  mkdir -p "$SIGN_DIR"

  if [[ ! -f "$SIGN_KEYSTORE" ]]; then
    "$JAVA_HOME/bin/keytool" -genkeypair \
      -alias "$SIGN_ALIAS" \
      -keyalg RSA \
      -keysize 2048 \
      -sigalg SHA256withRSA \
      -validity 3650 \
      -storetype PKCS12 \
      -keystore "$SIGN_KEYSTORE" \
      -storepass "$SIGN_STOREPASS" \
      -keypass "$SIGN_KEYPASS" \
      -dname "$SIGN_DNAME" \
      >/dev/null
    echo "✓ Created local signing keystore: $SIGN_KEYSTORE"
  fi

  "$JAVA_HOME/bin/jarsigner" \
    -keystore "$SIGN_KEYSTORE" \
    -storetype PKCS12 \
    -storepass "$SIGN_STOREPASS" \
    -keypass "$SIGN_KEYPASS" \
    "$PLUGIN_JAR" "$SIGN_ALIAS" \
    >/dev/null

  "$JAVA_HOME/bin/jarsigner" \
    -keystore "$SIGN_KEYSTORE" \
    -storetype PKCS12 \
    -storepass "$SIGN_STOREPASS" \
    -keypass "$SIGN_KEYPASS" \
    "$FEATURE_JAR" "$SIGN_ALIAS" \
    >/dev/null

  "$JAVA_HOME/bin/jarsigner" -verify "$PLUGIN_JAR" >/dev/null
  "$JAVA_HOME/bin/jarsigner" -verify "$FEATURE_JAR" >/dev/null
  echo "✓ JAR signatures added (alias: $SIGN_ALIAS)"
else
  echo ""
  echo "Step 2.5: Signing disabled (PLAINDB_SIGN_UPDATE_SITE=0)"
fi

# Step 3: Generate p2 metadata
echo ""
echo "Step 3: Generating p2 metadata files..."

PLUGIN_SIZE=$(stat -f%z "$PLUGIN_JAR" 2>/dev/null || stat -c%s "$PLUGIN_JAR" 2>/dev/null)
FEATURE_SIZE=$(stat -f%z "$FEATURE_JAR" 2>/dev/null || stat -c%s "$FEATURE_JAR" 2>/dev/null)

cat > "$UPDATE_SITE_DIR/content.xml" << 'CONTENT_EOL'
<?xml version="1.0" encoding="UTF-8"?>
<?metadataRepository version="1.0.0"?>
<repository name="PlainDB Local Update Site" type="org.eclipse.equinox.internal.p2.metadata.repository.LocalMetadataRepository" version="1.0.0"
    xmlns="http://www.eclipse.org/equinox/p2/metadata/repository/2.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.eclipse.org/equinox/p2/metadata/repository/2.0 http://www.eclipse.org/equinox/p2/2.0/metadata.xsd ">

  <properties size="3">
    <property name="artifact.repo.connection.factory" value="org.eclipse.equinox.p2.artifact.repository.file.FileArtifactRepositoryFactory"/>
    <property name="p2.compressed" value="false"/>
    <property name="p2.timestamp" value="1619203200000"/>
  </properties>

  <units size="3">
    <!-- Feature Unit -->
    <unit id="com.plaindb.dbeaver.feature.feature.group" version="1.0.0" singleton="false">
      <update id="com.plaindb.dbeaver.feature.feature.group" range="[0.0.0,1.0.0)" severity="0"/>
      <properties size="3">
        <property name="org.eclipse.equinox.p2.name" value="PlainDB DBeaver Plugin"/>
        <property name="org.eclipse.equinox.p2.description" value="DBeaver plugin for PlainDB SQL verification and request handling."/>
        <property name="org.eclipse.equinox.p2.provider" value="PlainDB"/>
      </properties>
      <provides size="1">
        <provided namespace="org.eclipse.equinox.p2.iu" name="com.plaindb.dbeaver.feature.feature.group" version="1.0.0"/>
      </provides>
      <filter/>
      <artifacts size="1">
        <artifact classifier="org.eclipse.update.feature" id="com.plaindb.dbeaver.feature" version="1.0.0"/>
      </artifacts>
      <touchpoint id="org.eclipse.equinox.p2.generic" version="1.0.0"/>
      <touchpointData size="1">
        <instructions size="1">
          <instruction key="install" value=""/>
        </instructions>
      </touchpointData>
      <requires size="1">
        <requirement namespace="org.eclipse.equinox.p2.iu" name="com.plaindb.dbeaver.feature.feature.jar" range="[1.0.0,1.0.0]" greedy="true"/>
      </requires>
    </unit>

    <!-- Feature JAR Unit -->
    <unit id="com.plaindb.dbeaver.feature.feature.jar" version="1.0.0" singleton="false">
      <properties size="2">
        <property name="org.eclipse.equinox.p2.name" value="PlainDB DBeaver Plugin"/>
        <property name="org.eclipse.equinox.p2.provider" value="PlainDB"/>
      </properties>
      <provides size="2">
        <provided namespace="org.eclipse.equinox.p2.iu" name="com.plaindb.dbeaver.feature.feature.jar" version="1.0.0"/>
        <provided namespace="org.eclipse.update.feature" name="com.plaindb.dbeaver.feature" version="1.0.0"/>
      </provides>
      <filter/>
      <artifacts size="1">
        <artifact classifier="org.eclipse.update.feature" id="com.plaindb.dbeaver.feature" version="1.0.0"/>
      </artifacts>
      <touchpoint id="org.eclipse.equinox.p2.eclipse.type" version="1.0.0"/>
      <touchpointData size="1">
        <instructions size="1">
          <instruction key="zipped" value="true"/>
        </instructions>
      </touchpointData>
      <requires size="1">
        <requirement namespace="org.eclipse.equinox.p2.iu" name="com.plaindb.dbeaver" range="[0.1.0.qualifier,0.1.0.qualifier]" greedy="true"/>
      </requires>
    </unit>

    <!-- Plugin Unit -->
    <unit id="com.plaindb.dbeaver" version="0.1.0.qualifier" singleton="true">
      <properties size="2">
        <property name="org.eclipse.equinox.p2.name" value="PlainDB DBeaver Plugin"/>
        <property name="org.eclipse.equinox.p2.provider" value="PlainDB"/>
      </properties>
      <provides size="1">
        <provided namespace="org.eclipse.equinox.p2.iu" name="com.plaindb.dbeaver" version="0.1.0.qualifier"/>
      </provides>
      <filter/>
      <artifacts size="1">
        <artifact classifier="osgi.bundle" id="com.plaindb.dbeaver" version="0.1.0.qualifier"/>
      </artifacts>
      <touchpoint id="org.eclipse.equinox.p2.osgi" version="1.0.0"/>
      <touchpointData size="1">
        <instructions size="2">
          <instruction key="install" value="method:installBundle(bundle:${artifact})"/>
          <instruction key="uninstall" value="method:uninstallBundle(bundle:${artifact})"/>
        </instructions>
      </touchpointData>
      <requires size="5">
        <requirement namespace="osgi.bundle" name="org.eclipse.core.runtime" range="0.0.0"/>
        <requirement namespace="osgi.bundle" name="org.eclipse.ui" range="0.0.0"/>
        <requirement namespace="osgi.bundle" name="org.eclipse.jface" range="0.0.0"/>
        <requirement namespace="osgi.bundle" name="org.eclipse.swt" range="0.0.0"/>
        <requirement namespace="osgi.bundle" name="org.jkiss.dbeaver.core" range="0.0.0" optional="true"/>
      </requires>
    </unit>
  </units>

</repository>
CONTENT_EOL

cat > "$UPDATE_SITE_DIR/artifacts.xml" << ARTIFACTS_EOL
<?xml version="1.0" encoding="UTF-8"?>
<?artifactRepository version="1.0.0"?>
<repository name="PlainDB Local Update Site" type="org.eclipse.equinox.internal.p2.artifact.repository.simpleRepository" version="1.0.0">
  <properties size="2">
    <property name="p2.compressed" value="false"/>
    <property name="p2.timestamp" value="1619203200000"/>
  </properties>
  <mappings size="2">
    <rule filter="(&amp; (classifier=osgi.bundle))" output='\${repoUrl}/plugins/\${id}_\${version}.jar'/>
    <rule filter="(&amp; (classifier=org.eclipse.update.feature))" output='\${repoUrl}/features/\${id}_\${version}.jar'/>
  </mappings>
  <artifacts size="2">
    <!-- Feature Artifact -->
    <artifact classifier="org.eclipse.update.feature" id="com.plaindb.dbeaver.feature" version="1.0.0">
      <properties size="2">
        <property name="artifact.size" value="$FEATURE_SIZE"/>
        <property name="download.size" value="$FEATURE_SIZE"/>
      </properties>
    </artifact>
    
    <!-- Plugin Artifact -->
    <artifact classifier="osgi.bundle" id="com.plaindb.dbeaver" version="0.1.0.qualifier">
      <properties size="2">
        <property name="artifact.size" value="$PLUGIN_SIZE"/>
        <property name="download.size" value="$PLUGIN_SIZE"/>
      </properties>
    </artifact>
  </artifacts>
</repository>
ARTIFACTS_EOL

echo "✓ Metadata files generated"

# Step 4: Summary
echo ""
echo "========================================="
echo "Update site ready!"
echo "========================================="
echo "Location: $UPDATE_SITE_DIR"
echo ""
echo "Files created:"
ls -lh "$PLUGINS_DIR"/*.jar 2>/dev/null || echo "  (no plugin jars)"
ls -lh "$FEATURES_DIR"/*.jar 2>/dev/null || echo "  (no feature jars)"
echo ""
echo "p2 Metadata:"
ls -lh "$UPDATE_SITE_DIR/content.xml" "$UPDATE_SITE_DIR/artifacts.xml" 2>/dev/null
echo ""
echo "To install in DBeaver:"
echo "  1. Help → Install New Software..."
echo "  2. Click 'Add' button:"
echo "     Name: PlainDB Local"
echo "     Location: file://$UPDATE_SITE_DIR"
echo "  3. Select 'PlainDB' category"
echo "  4. Click Next → Finish"
echo ""
