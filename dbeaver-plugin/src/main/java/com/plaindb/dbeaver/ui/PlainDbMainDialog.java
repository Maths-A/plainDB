package com.plaindb.dbeaver.ui;

import com.plaindb.dbeaver.policy.EnglishOnlyGuard;
import com.plaindb.dbeaver.service.SqlGeneratorClient;
import org.eclipse.jface.dialogs.Dialog;
import org.eclipse.jface.dialogs.IDialogConstants;
import org.eclipse.jface.dialogs.MessageDialog;
import org.eclipse.swt.SWT;
import org.eclipse.swt.events.SelectionAdapter;
import org.eclipse.swt.events.SelectionEvent;
import org.eclipse.swt.layout.GridData;
import org.eclipse.swt.layout.GridLayout;
import org.eclipse.swt.widgets.*;
import org.eclipse.jface.viewers.CellEditor;
import org.eclipse.jface.viewers.ColumnLabelProvider;
import org.eclipse.jface.viewers.IStructuredContentProvider;
import org.eclipse.jface.viewers.TableViewer;
import org.eclipse.jface.viewers.TableViewerColumn;
import org.eclipse.jface.viewers.TextCellEditor;
import org.eclipse.jface.viewers.ICellModifier;
import org.eclipse.jface.viewers.Viewer;
import org.jkiss.dbeaver.model.DBPDataSource;
import org.jkiss.dbeaver.model.DBPDataSourceContainer;
import org.jkiss.dbeaver.model.exec.DBCAttributeMetaData;
import org.jkiss.dbeaver.model.exec.DBCExecutionContext;
import org.jkiss.dbeaver.model.exec.DBCExecutionPurpose;
import org.jkiss.dbeaver.model.exec.DBCResultSet;
import org.jkiss.dbeaver.model.exec.DBCResultSetMetaData;
import org.jkiss.dbeaver.model.exec.DBCSession;
import org.jkiss.dbeaver.model.exec.DBCStatement;
import org.jkiss.dbeaver.model.exec.DBCStatementType;
import org.jkiss.dbeaver.model.runtime.DBRProgressMonitor;
import org.jkiss.dbeaver.model.runtime.VoidProgressMonitor;
import org.jkiss.dbeaver.model.struct.DBSInstance;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class PlainDbMainDialog extends Dialog {
    private static final int ROLLBACK_ID = IDialogConstants.CLIENT_ID + 1;
    private static final String DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";

    private Text apiKeyText;
    private Combo modelCombo;
    private Text backendUrlText;
    private Label backendStatusLabel;
    private Combo databaseCombo;
    private Text promptText;
    private Text outputText; // short status / messages
    private Button executeButton;
    private Button showSqlButton;
    private Button applyEditsButton;
    private Combo rollbackCombo;
    private Button rollbackSelectedButton;
    private TableViewer resultTableViewer;
    private List<RowData> resultRows = new ArrayList<>();
    private String[] resultColumnNames = new String[0];
    private Text historyText;
    private final Label[] stepBubbles = new Label[5];
    
    private String apiKey;
    private String selectedDatabase;
    private String selectedDatabaseType;
    private String prompt;
    private String output;
    private String lastGeneratedSql;
    private boolean requestGenerated;
    private StringBuilder requestHistory = new StringBuilder();
    private final List<DBPDataSourceContainer> databaseTargets = new ArrayList<>();
    private final List<RollbackSnapshot> rollbackSnapshots = new ArrayList<>();
    private final EnglishOnlyGuard englishOnlyGuard = new EnglishOnlyGuard();

    public PlainDbMainDialog(Shell parentShell) {
        super(parentShell);
        setShellStyle(SWT.DIALOG_TRIM | SWT.RESIZE | SWT.MAX);
    }

    @Override
    protected void configureShell(Shell shell) {
        super.configureShell(shell);
        shell.setText("PlainDB SQL Assistant");
        shell.setSize(800, 700);
    }

    @Override
    protected Control createDialogArea(Composite parent) {
        Composite container = (Composite) super.createDialogArea(parent);
        container.setLayout(new GridLayout(1, false));

        // === Create TabFolder ===
        TabFolder tabFolder = new TabFolder(container, SWT.NONE);
        tabFolder.setLayoutData(new GridData(SWT.FILL, SWT.FILL, true, true));

        // === SQL Assistant Tab (FIRST) ===
        TabItem sqlTab = new TabItem(tabFolder, SWT.NONE);
        sqlTab.setText("SQL Assistant");
        Composite sqlComp = createSqlTab(tabFolder);
        sqlTab.setControl(sqlComp);

        // === Account Tab ===
        TabItem accountTab = new TabItem(tabFolder, SWT.NONE);
        accountTab.setText("Account");
        Composite accountComp = createAccountTab(tabFolder);
        accountTab.setControl(accountComp);

        // === History Tab ===
        TabItem historyTab = new TabItem(tabFolder, SWT.NONE);
        historyTab.setText("Request History");
        Composite historyComp = createHistoryTab(tabFolder);
        historyTab.setControl(historyComp);

        // === About Tab (last) ===
        TabItem aboutTab = new TabItem(tabFolder, SWT.NONE);
        aboutTab.setText("About");
        Composite aboutComp = createAboutTab(tabFolder);
        aboutTab.setControl(aboutComp);

        return container;
    }

    private Composite createAccountTab(TabFolder parent) {
        Composite container = new Composite(parent, SWT.NONE);
        container.setLayout(new GridLayout(2, false));

        // === Backend URL and Connect ===
        Label backendUrlLabel = new Label(container, SWT.NONE);
        backendUrlLabel.setText("Backend URL:");
        backendUrlLabel.setLayoutData(new GridData(SWT.LEFT, SWT.CENTER, false, false));

        Composite backendRow = new Composite(container, SWT.NONE);
        backendRow.setLayout(new GridLayout(2, false));
        backendRow.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));

        backendUrlText = new Text(backendRow, SWT.BORDER);
        backendUrlText.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));
        backendUrlText.setText(DEFAULT_BACKEND_URL);
        backendUrlText.setMessage("https://<your-backend>/ (Cloud Function, Cloud Run, local backend, etc.)");

        Button connectBackendButton = new Button(backendRow, SWT.PUSH);
        connectBackendButton.setText("Connect Backend");
        connectBackendButton.setLayoutData(new GridData(SWT.RIGHT, SWT.CENTER, false, false));
        connectBackendButton.addSelectionListener(new SelectionAdapter() {
            @Override
            public void widgetSelected(SelectionEvent e) {
                testBackendConnection();
            }
        });

        backendStatusLabel = new Label(container, SWT.NONE);
        GridData backendStatusData = new GridData(SWT.FILL, SWT.CENTER, true, false);
        backendStatusData.horizontalSpan = 2;
        backendStatusLabel.setLayoutData(backendStatusData);
        backendStatusLabel.setText("Backend status: not connected yet");

        // === Model Selection ===
        Label modelLabel = new Label(container, SWT.NONE);
        modelLabel.setText("LLM Model:");
        modelLabel.setLayoutData(new GridData(SWT.LEFT, SWT.CENTER, false, false));

        modelCombo = new Combo(container, SWT.DROP_DOWN | SWT.READ_ONLY);
        modelCombo.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));
        modelCombo.setItems(new String[] { "gemini-2.5-flash" });
        modelCombo.select(0);

        // === API Key Section ===
        Label apiKeyLabel = new Label(container, SWT.NONE);
        apiKeyLabel.setText("API Key:");
        apiKeyLabel.setLayoutData(new GridData(SWT.LEFT, SWT.CENTER, false, false));

        apiKeyText = new Text(container, SWT.BORDER | SWT.PASSWORD);
        apiKeyText.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));
        apiKeyText.setMessage("Enter your Gemini API key (AIza...) or OAuth token");

        // === API Status Info ===
        Label infoLabel = new Label(container, SWT.WRAP);
        GridData infoData = new GridData(SWT.FILL, SWT.TOP, true, true);
        infoData.horizontalSpan = 2;
        infoData.heightHint = 150;
        infoLabel.setLayoutData(infoData);
        infoLabel.setText(
            "Account Setup:\n\n" +
            "1) Enter your backend URL and click 'Connect Backend'.\n" +
            "   Example local URL: http://127.0.0.1:8000\n" +
            "   Example cloud URL: https://<your-cloud-function-or-service>\n\n" +
            "2) Choose an available model.\n" +
            "   Currently supported: gemini-2.5-flash\n\n" +
            "3) Enter your Gemini API key (or OAuth token).\n\n" +
            "Notes:\n" +
            "• If backend URL points to a PlainDB backend, it should expose /health and /api/v1/generate-sql.\n" +
            "• If backend URL is empty, the plugin uses Gemini's public API endpoints.\n" +
            "• For production on Google Cloud, prefer short-lived OAuth tokens over long-lived API keys.\n"
        );

        return container;
    }

    private void testBackendConnection() {
        if (backendUrlText == null || backendStatusLabel == null) {
            return;
        }

        String baseUrl = backendUrlText.getText() == null ? "" : backendUrlText.getText().trim();
        if (baseUrl.isBlank()) {
            backendStatusLabel.setText("Backend status: URL is empty");
            return;
        }

        Integer healthCode = pingEndpoint(baseUrl + "/health");
        if (healthCode != null) {
            if (healthCode >= 200 && healthCode < 300) {
                backendStatusLabel.setText("Backend status: connected (health " + healthCode + ")");
            } else {
                backendStatusLabel.setText("Backend status: reachable, health returned " + healthCode);
            }
            return;
        }

        Integer baseCode = pingEndpoint(baseUrl);
        if (baseCode != null) {
            backendStatusLabel.setText("Backend status: base URL reachable (" + baseCode + ")");
        } else {
            backendStatusLabel.setText("Backend status: connection failed");
        }
    }

    private Integer pingEndpoint(String urlText) {
        try {
            java.net.URL url = new java.net.URL(urlText);
            java.net.HttpURLConnection conn = (java.net.HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(5000);
            return conn.getResponseCode();
        } catch (Exception ignored) {
            return null;
        }
    }

    private Composite createSqlTab(Composite parent) {
        Composite container = new Composite(parent, SWT.NONE);
        container.setLayout(new GridLayout(2, false));

        // === Database Selection Section (with refresh button) ===
        Label dbLabel = new Label(container, SWT.NONE);
        dbLabel.setText("Database target:");
        dbLabel.setLayoutData(new GridData(SWT.LEFT, SWT.CENTER, false, false));

        // Composite to hold combo and refresh button
        Composite dbComposite = new Composite(container, SWT.NONE);
        dbComposite.setLayout(new GridLayout(2, false));
        dbComposite.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));

        databaseCombo = new Combo(dbComposite, SWT.DROP_DOWN | SWT.READ_ONLY);
        databaseCombo.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));
        refreshDatabaseTargets();
        databaseCombo.addSelectionListener(new SelectionAdapter() {
            @Override
            public void widgetSelected(SelectionEvent e) {
                updateSelectedDatabaseTarget();
            }
        });

        // Refresh button
        Button refreshButton = new Button(dbComposite, SWT.PUSH);
        refreshButton.setText("⟲");
        GridData refreshButtonData = new GridData(SWT.RIGHT, SWT.CENTER, false, false);
        refreshButtonData.widthHint = 35;
        refreshButton.setLayoutData(refreshButtonData);
        refreshButton.addSelectionListener(new SelectionAdapter() {
            @Override
            public void widgetSelected(SelectionEvent e) {
                refreshDatabaseTargets();
                outputText.setText("Database targets refreshed.");
            }
        });

        // === Request/Prompt Section ===
        Label promptLabel = new Label(container, SWT.NONE);
        promptLabel.setText("Request (English):");
        GridData promptLabelData = new GridData(SWT.LEFT, SWT.TOP, false, false);
        promptLabelData.verticalAlignment = SWT.TOP;
        promptLabelData.verticalIndent = 5;
        promptLabel.setLayoutData(promptLabelData);

        promptText = new Text(container, SWT.BORDER | SWT.MULTI | SWT.WRAP | SWT.V_SCROLL);
        GridData promptData = new GridData(SWT.FILL, SWT.FILL, true, true);
        promptData.heightHint = 68;
        promptText.setLayoutData(promptData);
        promptText.setMessage("Describe what SQL operation you want to perform");

        // === Action Row ===
        Composite actionRow = new Composite(container, SWT.NONE);
        actionRow.setLayout(new GridLayout(3, false));
        GridData actionRowData = new GridData(SWT.FILL, SWT.CENTER, true, false);
        actionRowData.horizontalSpan = 2;
        actionRow.setLayoutData(actionRowData);

        executeButton = new Button(actionRow, SWT.PUSH);
        executeButton.setText("Execute request");
        executeButton.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));
        executeButton.addSelectionListener(new SelectionAdapter() {
            @Override
            public void widgetSelected(SelectionEvent e) {
                executeRequest();
            }
        });

        showSqlButton = new Button(actionRow, SWT.PUSH);
        showSqlButton.setText("Show Generated SQL");
        showSqlButton.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, false, false));
        showSqlButton.setEnabled(false);
        showSqlButton.addSelectionListener(new SelectionAdapter() {
            @Override
            public void widgetSelected(SelectionEvent e) {
                showGeneratedSql();
            }
        });

        Composite bubbleRow = new Composite(actionRow, SWT.NONE);
        bubbleRow.setLayout(new GridLayout(9, false));
        bubbleRow.setLayoutData(new GridData(SWT.RIGHT, SWT.CENTER, false, false));
        createStepBubbles(bubbleRow);

        // === Output Section ===
        Label outputLabel = new Label(container, SWT.NONE);
        outputLabel.setText("Output:");
        GridData outputLabelData = new GridData(SWT.LEFT, SWT.TOP, false, false);
        outputLabelData.verticalIndent = 5;
        outputLabel.setLayoutData(outputLabelData);

        outputText = new Text(container, SWT.BORDER | SWT.MULTI | SWT.WRAP | SWT.V_SCROLL | SWT.READ_ONLY);
        GridData outputData = new GridData(SWT.FILL, SWT.CENTER, true, false);
        outputData.heightHint = 24;
        outputText.setLayoutData(outputData);

        Label resultLabel = new Label(container, SWT.NONE);
        resultLabel.setText("Table result:");
        GridData resultLabelData = new GridData(SWT.LEFT, SWT.TOP, false, false);
        resultLabelData.verticalIndent = 5;
        resultLabel.setLayoutData(resultLabelData);

        // Create a TableViewer in the second column for editable, scrollable results
        resultTableViewer = new TableViewer(container, SWT.BORDER | SWT.FULL_SELECTION | SWT.V_SCROLL | SWT.H_SCROLL);
        Table table = resultTableViewer.getTable();
        table.setHeaderVisible(true);
        table.setLinesVisible(true);
        GridData tableData = new GridData(SWT.FILL, SWT.FILL, true, true);
        table.setLayoutData(tableData);
        // Content provider and label provider will be configured when filling data

        Composite applyRow = new Composite(container, SWT.NONE);
        applyRow.setLayout(new GridLayout(1, false));
        GridData applyRowData = new GridData(SWT.RIGHT, SWT.CENTER, true, false);
        applyRowData.horizontalSpan = 2;
        applyRow.setLayoutData(applyRowData);

        applyEditsButton = new Button(applyRow, SWT.PUSH);
        applyEditsButton.setText("Apply Edits");
        GridData applyBtnData = new GridData(SWT.RIGHT, SWT.CENTER, false, false);
        applyBtnData.exclude = true;
        applyEditsButton.setLayoutData(applyBtnData);
        applyEditsButton.setVisible(false);
        applyEditsButton.setEnabled(false);
        applyEditsButton.addSelectionListener(new SelectionAdapter() {
            @Override
            public void widgetSelected(SelectionEvent e) {
                try {
                    applyTableEditsToDatabase();
                } catch (Exception ex) {
                    outputText.setText("Apply failed: " + ex.getMessage());
                }
            }
        });

        rollbackSnapshots.clear();
        refreshRollbackChooser();
        resetStepBubbles();

        return container;
    }

    private Composite createHistoryTab(Composite parent) {
        Composite container = new Composite(parent, SWT.NONE);
        container.setLayout(new GridLayout(1, false));

        Label titleLabel = new Label(container, SWT.NONE);
        titleLabel.setText("Request History");
        titleLabel.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));

        historyText = new Text(container, SWT.BORDER | SWT.MULTI | SWT.WRAP | SWT.V_SCROLL | SWT.READ_ONLY);
        GridData historyData = new GridData(SWT.FILL, SWT.FILL, true, true);
        historyData.heightHint = 300;
        historyText.setLayoutData(historyData);
        historyText.setText("No requests yet...\n\nRequests will be tracked with timestamp and database target.");

        Composite rollbackRow = new Composite(container, SWT.NONE);
        rollbackRow.setLayout(new GridLayout(3, false));
        rollbackRow.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));

        Label rollbackLabel = new Label(rollbackRow, SWT.NONE);
        rollbackLabel.setText("Rollback snapshot:");

        rollbackCombo = new Combo(rollbackRow, SWT.DROP_DOWN | SWT.READ_ONLY);
        rollbackCombo.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));
        refreshRollbackChooser();

        rollbackSelectedButton = new Button(rollbackRow, SWT.PUSH);
        rollbackSelectedButton.setText("Rollback Selected");
        rollbackSelectedButton.setEnabled(false);
        rollbackSelectedButton.addSelectionListener(new SelectionAdapter() {
            @Override
            public void widgetSelected(SelectionEvent e) {
                rollbackSelectedSnapshot();
            }
        });

        // Clear History Button
        Button clearHistoryBtn = new Button(container, SWT.PUSH);
        clearHistoryBtn.setText("Clear History");
        clearHistoryBtn.setLayoutData(new GridData(SWT.RIGHT, SWT.CENTER, true, false));
        clearHistoryBtn.addSelectionListener(new SelectionAdapter() {
            @Override
            public void widgetSelected(SelectionEvent e) {
                requestHistory = new StringBuilder();
                rollbackSnapshots.clear();
                refreshRollbackChooser();
                historyText.setText("History cleared.");
            }
        });

        return container;
    }

    private Composite createAboutTab(TabFolder parent) {
        Composite container = new Composite(parent, SWT.NONE);
        container.setLayout(new GridLayout(1, false));

        Label titleLabel = new Label(container, SWT.NONE);
        titleLabel.setText("About PlainDB");
        titleLabel.setLayoutData(new GridData(SWT.FILL, SWT.CENTER, true, false));

        Text aboutText = new Text(container, SWT.BORDER | SWT.MULTI | SWT.WRAP | SWT.V_SCROLL | SWT.READ_ONLY);
        GridData aboutData = new GridData(SWT.FILL, SWT.FILL, true, true);
        aboutData.heightHint = 360;
        aboutText.setLayoutData(aboutData);
        aboutText.setText(
            "PlainDB helps you turn a natural-language request into SQL, run it on the selected database, and show the result in a table.\n\n" +
            "How the five steps work:\n\n" +
            "1. Intent\n" +
            "   PlainDB reads your request and figures out what you want. It expects a clear English sentence, such as 'show all rows from people'.\n\n" +
            "2. Safety\n" +
            "   The tool checks whether the request is safe and usable before generating SQL. This is where it can reject unclear, unsupported, or non-English input.\n\n" +
            "3. Target\n" +
            "   You choose the database connection that PlainDB should use. That tells the tool which schema to work against and where to execute the query.\n\n" +
            "4. API\n" +
            "   PlainDB sends the request to the configured AI backend or model. The AI writes SQL for the chosen database type.\n\n" +
            "5. SQL\n" +
            "   1) Semantic Verification - Ensures user intent matches generated SQL\n" +
            "   2) Safety Verification - Detects harmful or policy-violating SQL\n" +
            "   3) Transaction Execution - Runs SQL inside a transaction\n" +
            "   4) In-Transaction Effect - Validates changes match user intent\n" +
            "   5) Post-Commit Verification - Confirms final database state\n\n" +
            "If something fails other than an SQL-generation failure, PlainDB will try to explain the error in beginner-friendly language.\n\n" +
            "Extra notes:\n" +
            "- Use the Account tab to set the backend URL, model, and API key.\n" +
            "- Use Show Generated SQL to inspect the query before changing data.\n" +
            "- Use Apply Edits only when you want to save table changes back to the database.\n"
        );

        return container;
    }

    private void refreshDatabaseTargets() {
        databaseTargets.clear();
        if (databaseCombo == null) {
            return;
        }

        List<String> labels = new ArrayList<>();
        List<String> targetIds = new ArrayList<>();
        int globalRawCount = 0;
        int globalAddedCount = 0;
        int workspaceProjectCount = 0;
        int workspaceRawCount = 0;
        int workspaceAddedCount = 0;
        int activeRawCount = 0;
        int activeAddedCount = 0;

        try {
            Class<?> registryClass = Class.forName("org.jkiss.dbeaver.registry.DataSourceRegistry");
            Object allDataSourcesObj = registryClass.getMethod("getAllDataSources").invoke(null);
            if (allDataSourcesObj instanceof java.util.Collection) {
                java.util.Collection<?> dataSources = (java.util.Collection<?>) allDataSourcesObj;
                globalRawCount = dataSources.size();
                for (Object ds : dataSources) {
                    if (ds instanceof DBPDataSourceContainer) {
                        DBPDataSourceContainer container = (DBPDataSourceContainer) ds;
                        String id = container.getId();
                        if (id != null && targetIds.contains(id)) {
                            continue;
                        }
                        if (id != null) {
                            targetIds.add(id);
                        }
                        databaseTargets.add(container);
                        String label = formatDatabaseLabel(container);
                        if (!container.isConnected()) {
                            label += " [disconnected]";
                        }
                        labels.add(label);
                        globalAddedCount++;
                    }
                }
            }
        } catch (Throwable ignored) {
            // Keep going, workspace-level fallback below may still work.
        }

        // Note: DBWorkbench-based workspace/project discovery removed because
        // some DBeaver installations do not expose org.jkiss.dbeaver.runtime.DBWorkbench
        // to third-party bundles. We rely on DataSourceRegistry.getAllDataSources()
        // (above) which should return available connections when accessible.

        if (labels.isEmpty()) {
            databaseCombo.setItems(new String[] { "No databases configured" });
            databaseCombo.select(0);
            selectedDatabase = null;
            selectedDatabaseType = null;
            if (outputText != null) {
                outputText.setText("Debug: no databases discovered.\n\n" +
                    "Counts:\n" +
                    "- Global registry raw: " + globalRawCount + " | added: " + globalAddedCount + "\n" +
                    "- Workspace projects: " + workspaceProjectCount + "\n" +
                    "- Workspace registries raw: " + workspaceRawCount + " | added: " + workspaceAddedCount + "\n" +
                    "- Active project raw: " + activeRawCount + " | added: " + activeAddedCount + "\n\n" +
                    "If DBeaver shows a connection, open it once (expand tables) and reopen PlainDB.");
            }
            return;
        }

        databaseCombo.setItems(labels.toArray(new String[0]));
        databaseCombo.select(0);
        updateSelectedDatabaseTarget();
    }

    private void updateSelectedDatabaseTarget() {
        int index = databaseCombo.getSelectionIndex();
        if (index < 0 || index >= databaseTargets.size()) {
            selectedDatabase = null;
            selectedDatabaseType = null;
            return;
        }

        DBPDataSourceContainer container = databaseTargets.get(index);
        selectedDatabase = formatDatabaseLabel(container);
        selectedDatabaseType = inferDatabaseType(container);
    }

    private String formatDatabaseLabel(DBPDataSourceContainer container) {
        String name = container.getName();
        String driverName = container.getDriver() != null ? container.getDriver().getFullName() : "Unknown";
        return name + " (" + driverName + ")";
    }

    private String inferDatabaseType(DBPDataSourceContainer container) {
        if (container == null || container.getDriver() == null) {
            return "default";
        }
        String driverName = container.getDriver().getName();
        if (driverName != null) {
            String lower = driverName.toLowerCase();
            if (lower.contains("postgres")) return "postgresql";
            if (lower.contains("mysql")) return "mysql";
            if (lower.contains("sqlite")) return "sqlite";
            if (lower.contains("oracle")) return "oracle";
            if (lower.contains("mssql") || lower.contains("sql server")) return "mssql";
        }
        return "default";
    }

    private void createStepBubbles(Composite parent) {
        String[] stepLabels = new String[] {"Intent", "Safety", "Target", "API", "Done"};
        for (int i = 0; i < stepBubbles.length; i++) {
            stepBubbles[i] = new Label(parent, SWT.BORDER | SWT.CENTER);
            stepBubbles[i].setText(String.valueOf(i + 1));
            GridData bubbleData = new GridData(28, 28);
            bubbleData.horizontalAlignment = SWT.CENTER;
            bubbleData.verticalAlignment = SWT.CENTER;
            stepBubbles[i].setLayoutData(bubbleData);
            stepBubbles[i].setToolTipText((i + 1) + ". " + stepLabels[i]);

            if (i < stepBubbles.length - 1) {
                Label connector = new Label(parent, SWT.NONE);
                connector.setText("──");
                connector.setLayoutData(new GridData(SWT.CENTER, SWT.CENTER, false, false));
            }
        }
    }

    private void executeRequest() {
        String request = promptText.getText().trim();
        if (request.isEmpty()) {
            outputText.setText("Error: Please enter a request.");
            setStepState(0, StepState.FAIL);
            requestGenerated = false;
            return;
        }

        saveRollbackSnapshot("Before request: " + summarizeRequest(request));

        if (!englishOnlyGuard.isEnglishOnly(request)) {
            outputText.setText("Error: Request must be in English.");
            setStepState(0, StepState.FAIL);
            requestGenerated = false;
            return;
        }

        // Sync database selection before validation
        if (databaseCombo != null && databaseCombo.getSelectionIndex() >= 0) {
            updateSelectedDatabaseTarget();
        }

        if ((selectedDatabase == null || selectedDatabase.isBlank()) && !databaseTargets.isEmpty()) {
            selectedDatabase = formatDatabaseLabel(databaseTargets.get(0));
            selectedDatabaseType = inferDatabaseType(databaseTargets.get(0));
        }

        if (selectedDatabase == null || selectedDatabase.isBlank()) {
            outputText.setText("Error: Please select a connected database target.");
            setStepState(2, StepState.FAIL);
            requestGenerated = false;
            return;
        }

        if (selectedDatabaseType == null || selectedDatabaseType.isBlank()) {
            selectedDatabaseType = "default";
        }

        setStepState(0, StepState.PASS);
        setStepState(1, StepState.PASS);
        setStepState(2, StepState.PASS);
        setStepState(3, StepState.ACTIVE);

        performSqlGeneration(request);
    }

    private void performSqlGeneration(String request) {
        try {
            String apiKey = apiKeyText.getText();
            if (apiKey == null || apiKey.isBlank()) {
                outputText.setText("Error: Please provide a Gemini API key in Account tab.");
                setStepState(3, StepState.FAIL);
                setStepState(4, StepState.FAIL);
                return;
            }

            String apiProvider = "gemini";

            String endpointUrl = null;
            if (backendUrlText != null && !backendUrlText.getText().isBlank()) {
                endpointUrl = backendUrlText.getText().trim();
            }

            String llmModel = "gemini-2.5-flash";
            if (modelCombo != null && modelCombo.getSelectionIndex() >= 0) {
                llmModel = modelCombo.getText();
            }

            SqlGeneratorClient client = new SqlGeneratorClient(apiKey, apiProvider, endpointUrl, llmModel);
            String sql = client.generateSql(request, selectedDatabaseType);

            if (sql != null && !sql.isEmpty()) {
                lastGeneratedSql = sanitizeGeneratedSql(sql);
                // SQL generation succeeded -> API step is a pass
                setStepState(3, StepState.PASS);
                try {
                    String tableResult = executeSqlAndFormatTable(lastGeneratedSql);
                    outputText.setText(tableResult);
                    requestGenerated = true;
                    showSqlButton.setEnabled(true);
                    setStepState(4, StepState.PASS);

                    String timestamp = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss").format(new java.util.Date());
                    requestHistory.append("[").append(timestamp).append("] (").append(selectedDatabase).append(")\n")
                        .append("Request: ").append(promptText.getText()).append("\n")
                        .append("Output:\n").append(tableResult).append("\n\n")
                        .append("SQL: ").append(lastGeneratedSql).append("\n\n");
                    historyText.setText(requestHistory.toString());
                } catch (Exception execEx) {
                    // Execution failed (database error) — API call itself worked
                    outputText.setText(buildBeginnerFriendlyError(execEx, lastGeneratedSql));
                    showSqlButton.setEnabled(false);
                    setStepState(3, StepState.PASS);
                    setStepState(4, StepState.FAIL);
                    return;
                }
            } else {
                outputText.setText("Error: No SQL generated. Try again or check your backend.");
                showSqlButton.setEnabled(false);
                setStepState(3, StepState.FAIL);
                setStepState(4, StepState.FAIL);
            }
        } catch (Exception e) {
            outputText.setText(buildBeginnerFriendlyError(e, lastGeneratedSql));
            showSqlButton.setEnabled(false);
            setStepState(3, StepState.FAIL);
            setStepState(4, StepState.FAIL);
        }
    }

    private void showGeneratedSql() {
        if (lastGeneratedSql == null || lastGeneratedSql.isBlank()) {
            MessageDialog.openInformation(getShell(), "Generated SQL", "No SQL has been generated yet.");
            return;
        }
        MessageDialog.openInformation(getShell(), "Generated SQL", lastGeneratedSql);
    }

    private String executeSqlAndFormatTable(String sql) throws Exception {
        DBPDataSourceContainer container = getSelectedDataSourceContainer();
        if (container == null) {
            throw new IllegalStateException("No database selected.");
        }

        DBRProgressMonitor monitor = new VoidProgressMonitor();
        if (!container.isConnected()) {
            boolean connected = container.connect(monitor, true, false);
            if (!connected) {
                throw new IllegalStateException("Could not connect selected data source.");
            }
        }

        DBPDataSource dataSource = container.getDataSource();
        if (dataSource == null) {
            throw new IllegalStateException("Selected data source is not available.");
        }

        DBSInstance instance = dataSource.getDefaultInstance();
        if (instance == null) {
            throw new IllegalStateException("Could not resolve default database instance.");
        }

        DBCExecutionContext context = instance.getDefaultContext(monitor, true);
        if (context == null) {
            throw new IllegalStateException("Could not open execution context.");
        }

        try (DBCSession session = context.openSession(monitor, DBCExecutionPurpose.USER, "PlainDB table preview");
             DBCStatement statement = session.prepareStatement(DBCStatementType.QUERY, sql, false, false, false)) {
            statement.setLimit(0, 200);
            boolean hasResultSet = statement.executeStatement();
                if (hasResultSet) {
                try (DBCResultSet rs = statement.openResultSet()) {
                    // Populate editable table viewer and return a short summary
                    populateTableFromResultSet(rs, 200);
                    return "Displayed " + resultRows.size() + " row(s) in the result table.";
                }
            }
            long rowCount = statement.getUpdateRowCount();
            return "+----------------+\n"
                + "| RESULT         |\n"
                + "+----------------+\n"
                + "| Rows affected: " + rowCount + " |\n"
                + "+----------------+\n";
        }
    }

    private DBPDataSourceContainer getSelectedDataSourceContainer() {
        int index = databaseCombo != null ? databaseCombo.getSelectionIndex() : -1;
        if (index < 0 || index >= databaseTargets.size()) {
            return null;
        }
        return databaseTargets.get(index);
    }

    private String sanitizeGeneratedSql(String sql) {
        String trimmed = sql.trim();
        if (trimmed.startsWith("```")) {
            int firstNewLine = trimmed.indexOf('\n');
            if (firstNewLine >= 0) {
                trimmed = trimmed.substring(firstNewLine + 1);
            }
            if (trimmed.endsWith("```")) {
                trimmed = trimmed.substring(0, trimmed.length() - 3);
            }
        }
        return trimmed.trim();
    }

    // ------- Table model and helpers -------
    private static class RowData {
        Object[] cells;
        Object[] originalCells;
        RowData(int cols) { cells = new Object[cols]; originalCells = new Object[cols]; }
        void markOriginal() {
            if (cells == null) return;
            originalCells = new Object[cells.length];
            System.arraycopy(cells, 0, originalCells, 0, cells.length);
        }
        boolean changed() {
            if (cells == null || originalCells == null) return false;
            for (int i = 0; i < cells.length; i++) {
                Object a = cells[i];
                Object b = originalCells[i];
                if (a == null && b == null) continue;
                if (a == null || b == null) return true;
                if (!a.equals(b)) return true;
            }
            return false;
        }
    }

    private void buildTableColumns(String[] columnNames) {
        resultColumnNames = columnNames == null ? new String[0] : columnNames;
        Table table = resultTableViewer.getTable();
        // clear existing
        for (TableColumn c : table.getColumns()) {
            c.dispose();
        }
        resultRows.clear();

        for (int i = 0; i < resultColumnNames.length; i++) {
            final int colIndex = i;
            TableViewerColumn tvc = new TableViewerColumn(resultTableViewer, SWT.NONE);
            TableColumn tc = tvc.getColumn();
            tc.setText(resultColumnNames[i]);
            tc.setWidth(150);
            tvc.setLabelProvider(new ColumnLabelProvider() {
                @Override
                public String getText(Object element) {
                    if (element instanceof RowData) {
                        Object v = ((RowData) element).cells[colIndex];
                        return v == null ? "NULL" : String.valueOf(v);
                    }
                    return "";
                }
            });
        }

        resultTableViewer.setContentProvider(new IStructuredContentProvider() {
            @Override
            public Object[] getElements(Object inputElement) {
                return resultRows.toArray(new RowData[0]);
            }

            @Override public void dispose() {}
            @Override public void inputChanged(Viewer viewer, Object oldInput, Object newInput) {}
        });

        // make cells editable
        CellEditor[] editors = new CellEditor[resultColumnNames.length];
        for (int i = 0; i < editors.length; i++) {
            editors[i] = new TextCellEditor(resultTableViewer.getTable());
        }
        resultTableViewer.setCellEditors(editors);
        resultTableViewer.setColumnProperties(resultColumnNames);
        resultTableViewer.setCellModifier(new ICellModifier() {
            @Override
            public boolean canModify(Object element, String property) {
                return true;
            }

            @Override
            public Object getValue(Object element, String property) {
                RowData row = (RowData) element;
                for (int i = 0; i < resultColumnNames.length; i++) {
                    if (resultColumnNames[i].equals(property)) return row.cells[i] == null ? "" : String.valueOf(row.cells[i]);
                }
                return "";
            }

            @Override
            public void modify(Object element, String property, Object value) {
                if (element instanceof Item) element = ((Item) element).getData();
                if (!(element instanceof RowData)) return;
                RowData row = (RowData) element;
                for (int i = 0; i < resultColumnNames.length; i++) {
                    if (resultColumnNames[i].equals(property)) {
                        row.cells[i] = value;
                        resultTableViewer.update(row, null);
                        updateApplyEditsButtonVisibility();
                        return;
                    }
                }
            }
        });
    }

    private void populateTableFromResultSet(DBCResultSet rs, int maxRows) throws Exception {
        DBCResultSetMetaData meta = rs.getMeta();
        List<? extends DBCAttributeMetaData> attrs = meta == null ? java.util.Collections.emptyList() : meta.getAttributes();
        int cols = attrs.size();
        String[] colNames = new String[cols];
        for (int i = 0; i < cols; i++) {
            DBCAttributeMetaData a = attrs.get(i);
            String label = a == null ? null : a.getLabel();
            if (label == null || label.isBlank()) label = a == null ? ("col_" + (i+1)) : a.getName();
            colNames[i] = label;
        }
        buildTableColumns(colNames);

        int rowCount = 0;
        while (rs.nextRow() && rowCount < maxRows) {
            RowData r = new RowData(cols);
            for (int i = 0; i < cols; i++) {
                Object v = rs.getAttributeValue(i);
                r.cells[i] = v;
            }
            r.markOriginal();
            resultRows.add(r);
            rowCount++;
        }
        resultTableViewer.setInput(this);
        updateApplyEditsButtonVisibility();
    }

    private void applyTableEditsToDatabase() throws Exception {
        if (resultRows.isEmpty() || resultColumnNames.length == 0) {
            outputText.setText("No results to apply.");
            return;
        }
        saveRollbackSnapshot("Before table update: " + summarizeSql(lastGeneratedSql));
        // assume first column is primary key
        int pkIndex = 0;
        DBPDataSourceContainer container = getSelectedDataSourceContainer();
        if (container == null) throw new IllegalStateException("No database selected.");
        DBRProgressMonitor monitor = new VoidProgressMonitor();
        if (!container.isConnected()) {
            boolean connected = container.connect(monitor, true, false);
            if (!connected) throw new IllegalStateException("Could not connect selected data source.");
        }
        DBPDataSource dataSource = container.getDataSource();
        DBSInstance instance = dataSource.getDefaultInstance();
        DBCExecutionContext context = instance.getDefaultContext(monitor, true);

        int applied = 0;
        try (DBCSession session = context.openSession(monitor, DBCExecutionPurpose.USER, "PlainDB apply edits")) {
            for (RowData row : resultRows) {
                if (!row.changed()) continue;
                Object pkVal = row.originalCells[pkIndex];
                if (pkVal == null) continue; // cannot update without PK
                String tableName = inferTableNameFromSql(lastGeneratedSql);
                if (tableName.isBlank()) {
                    throw new IllegalStateException("Could not infer table name from generated SQL.");
                }
                StringBuilder sb = new StringBuilder();
                sb.append("UPDATE ").append(tableName).append(" SET ");
                boolean first = true;
                for (int i = 0; i < resultColumnNames.length; i++) {
                    if (i == pkIndex) continue;
                    Object current = row.cells[i];
                    Object original = row.originalCells[i];
                    if (!valuesDiffer(current, original)) {
                        continue;
                    }
                    if (!first) sb.append(", ");
                    sb.append(resultColumnNames[i]).append(" = ").append(toSqlLiteral(current));
                    first = false;
                }
                if (first) {
                    continue;
                }
                sb.append(" WHERE ").append(resultColumnNames[pkIndex]).append(" = '").append(escapeSql(String.valueOf(pkVal))).append("'");
                String updateSql = sb.toString();
                try (DBCStatement stmt = session.prepareStatement(DBCStatementType.QUERY, updateSql, false, false, false)) {
                    stmt.executeStatement();
                    applied++;
                    // mark current as original
                    row.markOriginal();
                } catch (Exception e) {
                    outputText.setText(buildBeginnerFriendlyError(e, updateSql));
                }
            }
        }
        outputText.setText("Table updated. Refreshed result table after applying edits to " + applied + " row(s).");
        updateApplyEditsButtonVisibility();
        // refresh view by re-running last generated SQL if available
        if (lastGeneratedSql != null && !lastGeneratedSql.isBlank()) {
            try {
                executeSqlAndFormatTable(lastGeneratedSql);
                outputText.setText("Table updated. Refreshed result table after applying edits to " + applied + " row(s).");
            } catch (Exception ignored) {
                outputText.setText("Table updated. The result table could not be refreshed, but the edit was submitted.");
            }
        }
    }

    private String escapeSql(String v) {
        if (v == null) return "";
        return v.replace("'", "''");
    }

    private String inferTableNameFromSql(String sql) {
        if (sql == null) return "";
        String text = sql.trim();
        Pattern fromPattern = Pattern.compile("(?i)\\bfrom\\s+([\\w\\.\"`]+)");
        Matcher fromMatcher = fromPattern.matcher(text);
        if (fromMatcher.find()) {
            return fromMatcher.group(1);
        }

        Pattern updatePattern = Pattern.compile("(?i)^\\s*update\\s+([\\w\\.\"`]+)");
        Matcher updateMatcher = updatePattern.matcher(text);
        if (updateMatcher.find()) {
            return updateMatcher.group(1);
        }
        return "";
    }

    private boolean valuesDiffer(Object left, Object right) {
        if (left == null && right == null) return false;
        if (left == null || right == null) return true;
        return !String.valueOf(left).equals(String.valueOf(right));
    }

    private String toSqlLiteral(Object value) {
        if (value == null) {
            return "NULL";
        }
        String text = String.valueOf(value);
        if (text.isBlank()) {
            return "''";
        }
        return "'" + escapeSql(text) + "'";
    }

    private void updateApplyEditsButtonVisibility() {
        if (applyEditsButton == null || applyEditsButton.isDisposed()) {
            return;
        }
        boolean hasChanges = false;
        for (RowData row : resultRows) {
            if (row.changed()) {
                hasChanges = true;
                break;
            }
        }
        Object data = applyEditsButton.getLayoutData();
        if (data instanceof GridData) {
            GridData gd = (GridData) data;
            gd.exclude = !hasChanges;
        }
        applyEditsButton.setVisible(hasChanges);
        applyEditsButton.setEnabled(hasChanges);
        Composite parent = applyEditsButton.getParent();
        if (parent != null && !parent.isDisposed()) {
            parent.layout(true, true);
        }
    }

    private String buildBeginnerFriendlyError(Exception e, String sqlContext) {
        String technicalMessage = e == null ? "Unknown error" : (e.getMessage() == null ? e.toString() : e.getMessage());
        try {
            String apiKey = apiKeyText == null ? null : apiKeyText.getText();
            if (apiKey == null || apiKey.isBlank()) {
                return "What happened: " + technicalMessage
                    + "\nWhy it happened: The database rejected the SQL or connection details."
                    + "\nHow to fix it now: Check selected database, table/column names, then try again.";
            }

            String endpointUrl = null;
            if (backendUrlText != null && backendUrlText.getText() != null && !backendUrlText.getText().isBlank()) {
                endpointUrl = backendUrlText.getText().trim();
            }

            String llmModel = "gemini-2.5-flash";
            if (modelCombo != null && modelCombo.getSelectionIndex() >= 0) {
                llmModel = modelCombo.getText();
            }

            SqlGeneratorClient client = new SqlGeneratorClient(apiKey, "gemini", endpointUrl, llmModel);
            String aiExplanation = client.explainDatabaseError(selectedDatabaseType, sqlContext, technicalMessage);
            if (aiExplanation != null && !aiExplanation.isBlank()) {
                // Validate AI output: reject obviously malformed explanations (e.g. unpaired quotes
                // or extremely short/empty responses that contain dangling placeholders).
                String trimmed = aiExplanation.trim();
                int quoteCount = 0;
                for (char c : trimmed.toCharArray()) if (c == '"') quoteCount++;
                boolean badQuotes = (quoteCount % 2) != 0;
                boolean tooShort = trimmed.length() < 12;
                boolean suspiciousEmptyQuoted = trimmed.contains("\"\"") || trimmed.matches(".*The table named\\s*\\\"\\s*.*");
                if (!badQuotes && !tooShort && !suspiciousEmptyQuoted) {
                    return aiExplanation;
                }
                // else fall through to static beginner message below
            }
        } catch (Exception ignored) {
            // fall back to static beginner message
        }

        return "What happened: " + technicalMessage
            + "\nWhy it happened: The SQL did not match the database schema or permissions."
            + "\nHow to fix it now: Open Show Generated SQL, verify table/column names, and retry.";
    }

    private String formatResultSetAsTable(DBCResultSet rs, int maxRows) throws Exception {
        DBCResultSetMetaData meta = rs.getMeta();
        List<? extends DBCAttributeMetaData> attributes = meta == null ? java.util.Collections.emptyList() : meta.getAttributes();
        int colCount = attributes.size();
        if (colCount == 0) {
            return "+--------+\n| RESULT |\n+--------+\n| Empty  |\n+--------+";
        }
        List<String[]> rows = new ArrayList<>();
        int[] widths = new int[colCount];

        for (int i = 0; i < colCount; i++) {
            DBCAttributeMetaData attr = attributes.get(i);
            String label = attr == null ? null : attr.getLabel();
            if (label == null || label.isBlank()) {
                label = attr == null ? ("col_" + (i + 1)) : attr.getName();
            }
            widths[i] = label == null ? 4 : label.length();
        }

        int rowCounter = 0;
        while (rs.nextRow() && rowCounter < maxRows) {
            String[] row = new String[colCount];
            for (int i = 0; i < colCount; i++) {
                Object value = rs.getAttributeValue(i);
                String text = value == null ? "NULL" : String.valueOf(value);
                if (text.length() > 80) {
                    text = text.substring(0, 77) + "...";
                }
                row[i] = text;
                widths[i] = Math.max(widths[i], text.length());
            }
            rows.add(row);
            rowCounter++;
        }

        StringBuilder sb = new StringBuilder();
        String border = buildBorder(widths);
        sb.append(border).append('\n');
        sb.append('|');
        for (int i = 0; i < colCount; i++) {
            DBCAttributeMetaData attr = attributes.get(i);
            String name = attr == null ? null : attr.getLabel();
            if (name == null || name.isBlank()) {
                name = attr == null ? ("col_" + (i + 1)) : attr.getName();
            }
            sb.append(' ').append(padRight(name, widths[i])).append(" |");
        }
        sb.append('\n').append(border).append('\n');

        for (String[] row : rows) {
            sb.append('|');
            for (int i = 0; i < colCount; i++) {
                sb.append(' ').append(padRight(row[i], widths[i])).append(" |");
            }
            sb.append('\n');
        }

        sb.append(border).append('\n');
        sb.append(rows.size()).append(" row(s)");
        if (rowCounter >= maxRows) {
            sb.append(" (truncated to ").append(maxRows).append(")");
        }
        return sb.toString();
    }

    private String buildBorder(int[] widths) {
        StringBuilder border = new StringBuilder("+");
        for (int width : widths) {
            for (int i = 0; i < width + 2; i++) {
                border.append('-');
            }
            border.append('+');
        }
        return border.toString();
    }

    private String padRight(String text, int width) {
        String safe = text == null ? "" : text;
        if (safe.length() >= width) {
            return safe;
        }
        StringBuilder sb = new StringBuilder(safe);
        while (sb.length() < width) {
            sb.append(' ');
        }
        return sb.toString();
    }

    private void setStepState(int step, StepState state) {
        if (step >= 0 && step < stepBubbles.length) {
            switch (state) {
                case PASS:
                    stepBubbles[step].setBackground(getShell().getDisplay().getSystemColor(SWT.COLOR_GREEN));
                    stepBubbles[step].setForeground(getShell().getDisplay().getSystemColor(SWT.COLOR_WHITE));
                    break;
                case FAIL:
                    stepBubbles[step].setBackground(getShell().getDisplay().getSystemColor(SWT.COLOR_RED));
                    stepBubbles[step].setForeground(getShell().getDisplay().getSystemColor(SWT.COLOR_WHITE));
                    break;
                case ACTIVE:
                    stepBubbles[step].setBackground(getShell().getDisplay().getSystemColor(SWT.COLOR_BLUE));
                    stepBubbles[step].setForeground(getShell().getDisplay().getSystemColor(SWT.COLOR_WHITE));
                    break;
                default:
                    stepBubbles[step].setBackground(null);
                    stepBubbles[step].setForeground(null);
            }
        }
    }

    private void resetStepBubbles() {
        for (Label bubble : stepBubbles) {
            bubble.setBackground(null);
            bubble.setForeground(null);
        }
    }

    private void saveRollbackSnapshot(String label) {
        if (promptText == null || outputText == null) {
            return;
        }
        rollbackSnapshots.add(new RollbackSnapshot(
            label,
            promptText.getText(),
            outputText.getText(),
            selectedDatabase,
            selectedDatabaseType
        ));
        refreshRollbackChooser();
    }

    private void refreshRollbackChooser() {
        if (rollbackCombo == null || rollbackCombo.isDisposed()) {
            return;
        }

        if (rollbackSnapshots.isEmpty()) {
            rollbackCombo.setItems(new String[] { "No rollback snapshots" });
            rollbackCombo.select(0);
            rollbackCombo.setEnabled(false);
            if (rollbackSelectedButton != null && !rollbackSelectedButton.isDisposed()) {
                rollbackSelectedButton.setEnabled(false);
            }
            return;
        }

        String[] items = new String[rollbackSnapshots.size()];
        for (int i = 0; i < rollbackSnapshots.size(); i++) {
            items[i] = rollbackSnapshots.get(i).displayLabel(i);
        }
        rollbackCombo.setItems(items);
        rollbackCombo.select(items.length - 1);
        rollbackCombo.setEnabled(true);
        if (rollbackSelectedButton != null && !rollbackSelectedButton.isDisposed()) {
            rollbackSelectedButton.setEnabled(true);
        }
    }

    private void rollbackSelectedSnapshot() {
        if (rollbackSnapshots.isEmpty() || rollbackCombo == null) {
            return;
        }

        int index = rollbackCombo.getSelectionIndex();
        if (index < 0 || index >= rollbackSnapshots.size()) {
            return;
        }

        RollbackSnapshot snapshot = rollbackSnapshots.get(index);
        promptText.setText(snapshot.prompt);
        outputText.setText(snapshot.output);
        selectedDatabase = snapshot.selectedDatabase;
        selectedDatabaseType = snapshot.selectedDatabaseType;
        resetStepBubbles();

        if (index < rollbackSnapshots.size() - 1) {
            rollbackSnapshots.subList(index + 1, rollbackSnapshots.size()).clear();
        }
        refreshRollbackChooser();
        historyText.setText(historyText.getText() + "\n\nRolled back to: " + snapshot.label);
    }

    private String summarizeRequest(String request) {
        if (request == null) {
            return "(empty)";
        }
        String trimmed = request.trim().replaceAll("\\s+", " ");
        if (trimmed.length() > 48) {
            return trimmed.substring(0, 45) + "...";
        }
        return trimmed;
    }

    private String summarizeSql(String sql) {
        if (sql == null || sql.isBlank()) {
            return "(no SQL)";
        }
        String compact = sql.trim().replaceAll("\\s+", " ");
        if (compact.length() > 48) {
            return compact.substring(0, 45) + "...";
        }
        return compact;
    }

    @Override
    protected void createButtonsForButtonBar(Composite parent) {
        createButton(parent, IDialogConstants.OK_ID, "Close", true);
        createButton(parent, ROLLBACK_ID, "Rollback", false);
    }

    @Override
    protected void buttonPressed(int buttonId) {
        if (buttonId == ROLLBACK_ID) {
            if (!rollbackSnapshots.isEmpty()) {
                RollbackSnapshot previous = rollbackSnapshots.remove(rollbackSnapshots.size() - 1);
                promptText.setText(previous.prompt);
                outputText.setText(previous.output);
                selectedDatabase = previous.selectedDatabase;
                selectedDatabaseType = previous.selectedDatabaseType;
                resetStepBubbles();
                refreshRollbackChooser();
            }
        } else {
            super.buttonPressed(buttonId);
        }
    }

    private enum StepState {
        PASS, FAIL, ACTIVE
    }

    private static class RollbackSnapshot {
        String label;
        String prompt;
        String output;
        String selectedDatabase;
        String selectedDatabaseType;

        RollbackSnapshot(String label, String prompt, String output, String selectedDatabase, String selectedDatabaseType) {
            this.label = label;
            this.prompt = prompt;
            this.output = output;
            this.selectedDatabase = selectedDatabase;
            this.selectedDatabaseType = selectedDatabaseType;
        }

        String displayLabel(int index) {
            return (index + 1) + ": " + label;
        }
    }

}
