package com.plaindb.dbeaver.ui;

import com.plaindb.dbeaver.model.PlainDbDecision;

public final class PlainDbStatusFormatter {
    public String format(PlainDbDecision decision) {
        if (decision.isApproved()) {
            return "PlainDB approved the request after " + decision.getAttempts() + " attempt(s).";
        }
        return "PlainDB rejected the request: " + decision.getMessage();
    }
}
