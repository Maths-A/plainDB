package com.plaindb.dbeaver.handlers;

import com.plaindb.dbeaver.ui.PlainDbMainDialog;
import org.eclipse.core.commands.AbstractHandler;
import org.eclipse.core.commands.ExecutionEvent;
import org.eclipse.core.commands.ExecutionException;
import org.eclipse.swt.widgets.Display;
import org.eclipse.swt.widgets.Shell;

public final class VerifyRequestHandler extends AbstractHandler {
    @Override
    public Object execute(ExecutionEvent event) throws ExecutionException {
        Display display = Display.getDefault();
        Shell shell = display != null ? display.getActiveShell() : null;
        if (shell == null) {
            return null;
        }

        PlainDbMainDialog dialog = new PlainDbMainDialog(shell);
        dialog.open();

        return null;
    }
}
