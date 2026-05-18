# PlainDB DBeaver Plugin Update Site

This directory contains a local p2 update site that allows installation of the PlainDB DBeaver plugin through DBeaver's standard "Install New Software" dialog.

## Structure

- **features/** - Contains the feature descriptor JAR that bundles the plugin metadata
- **plugins/** - Contains the actual plugin JAR (com.plaindb.dbeaver)
- **site.xml** - p2 site descriptor listing available features and categories
- **category.xml** - Category descriptor for CLI tools

## Building the Update Site

```bash
cd /Users/maubert/Documents/UCSC/Research/plainDB
bash scripts/build-update-site.sh
```

This script:
1. Copies the compiled plugin JAR (from DBeaver installation)
2. Creates the feature JAR with metadata
3. Signs plugin and feature JARs with a local certificate (default)
4. Generates site descriptors

By default, signing uses a local keystore generated at:
- `update-site/.signing/plaindb-local-dev.p12`

Environment variables to customize signing:
- `PLAINDB_SIGN_UPDATE_SITE=0` to disable signing
- `PLAINDB_SIGN_ALIAS`
- `PLAINDB_SIGN_DNAME`
- `PLAINDB_SIGN_STOREPASS`
- `PLAINDB_SIGN_KEYPASS`
- `PLAINDB_SIGN_KEYSTORE`

## Installing via DBeaver's Software Installer

### Step 1: Add Update Site
1. Open DBeaver
2. Go to **Help → Install New Software...**
3. Click the **Add** button
4. Enter:
   - **Name:** `PlainDB Local`
   - **Location:** `file:///Users/maubert/Documents/UCSC/Research/plainDB/update-site`
5. Click **Add**

### Step 2: Select and Install
1. The "PlainDB" category should appear in the list
2. Check the **PlainDB** checkbox to expand it
3. Select **PlainDB DBeaver Plugin**
4. Click **Next**, then **Finish**
5. Accept the license agreement
6. Restart DBeaver when prompted

### Step 3: Verify Installation
1. Open a SQL editor in any database connection
2. Look for the **PlainDB** menu or command in the SQL editor menu
3. The "Verify database request" command should be available

## How This Works

This is a **p2 repository** - Eclipse's provisioning platform. DBeaver uses p2 for software installation management.

- **Feature JAR** defines what gets installed (describes dependencies, metadata, version)
- **Plugin JAR** contains the actual code
- **site.xml** tells p2 what features are available in this repository
- **File URL** allows p2 to treat a local directory as an update site

Once installed, the plugin becomes part of DBeaver's core plugins and updates through the normal Help → Check for Updates workflow.

## Version Info

- **Plugin Version:** 0.1.0.qualifier
- **Feature Version:** 1.0.0
- **Target:** DBeaver 26+, Java 21+, Eclipse RCP 4.x

## Troubleshooting

**Plugin doesn't appear in "Install New Software":**
- Verify the file URL in step 1 is correct (check for typos)
- Ensure both JARs exist in the update site:
  - `update-site/plugins/com.plaindb.dbeaver_0.1.0.qualifier.jar`
  - `update-site/features/com.plaindb.dbeaver.feature_1.0.0.jar`

**Installation fails with "bundle not found":**
- Make sure DBeaver is properly targeting Java 21: `-Duser.timezone=UTC` should be in `dbeaver.ini`
- Run `scripts/build-update-site.sh` again to ensure latest plugin is copied

**Plugin still not visible after restart:**
- Check DBeaver's **Help → About → Installation Details → Features** tab
- If listed but not functional, check the Error Log (**Help → Show Error Log**) for bundle errors
- Alternatively, use `scripts/run-local-dbeaver.sh` to do a fresh install to the DBeaver plugins directory
