package com.plaindb.dbeaver.handlers;

import com.plaindb.dbeaver.policy.EnglishOnlyGuard;
import com.plaindb.dbeaver.service.PlainDbServiceClient;
import com.plaindb.dbeaver.ui.PlainDbRequestDialog;
import com.plaindb.dbeaver.request.PlainDbRequest;
import com.plaindb.dbeaver.decision.PlainDbDecision;
import org.eclipse.core.commands.AbstractHandler;
import org.eclipse.core.commands.ExecutionEvent;
import org.eclipse.core.commands.ExecutionException;
import org.eclipse.jface.dialogs.MessageDialog;
import org.eclipse.swt.widgets.Display;
import org.eclipse.swt.widgets.Shell;

public final class VerifyRequestHandler extends AbstractHandler {
    private static final String TITLE = "PlainDB";

    private final EnglishOnlyGuard englishOnlyGuard = new EnglishOnlyGuard();
    private final PlainDbServiceClient client = new PlainDbServiceClient("http://127.0.0.1:8787");

    @Override
    public Object execute(ExecutionEvent event) throws ExecutionException {
        String connectionName = "Default connection";
        String prompt = openRequestDialog();

        if (prompt == null || prompt.isBlank()) {
            showInfo(TITLE, "No request was entered.");
            return null;
        }

        if (!englishOnlyGuard.isEnglishOnly(prompt)) {
            showInfo(TITLE, "Please write the request in English.");
            return null;
        }

        PlainDbDecision decision = client.verify(new PlainDbRequest(prompt, connectionName));
        showInfo(TITLE, decision.getMessage());
        return null;
    }

    private String openRequestDialog() {
        Display display = Display.getDefault();
        Shell shell = display != null ? display.getActiveShell() : null;
        if (shell == null) {
            return null;
        }

        PlainDbRequestDialog dialog = new PlainDbRequestDialog(shell);
        if (dialog.open() != org.eclipse.jface.window.Window.OK) {
            return null;
        }

        return dialog.getPrompt();
    }

    private void showInfo(String title, String message) {
        Display display = Display.getDefault();
        Shell shell = display != null ? display.getActiveShell() : null;
        MessageDialog.openInformation(shell, title, message);
    }
}
