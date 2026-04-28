package com.plaindb.dbeaver.model;

public final class PlainDbDecision {
    private final boolean approved;
    private final String message;
    private final int attempts;

    public PlainDbDecision(boolean approved, String message, int attempts) {
        this.approved = approved;
        this.message = message;
        this.attempts = attempts;
    }

    public boolean isApproved() {
        return approved;
    }

    public String getMessage() {
        return message;
    }

    public int getAttempts() {
        return attempts;
    }
}
