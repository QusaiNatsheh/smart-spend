from django.urls import path

from . import views

urlpatterns = [
    path("", views.home_page, name="home"),
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("expense/add/", views.add_expense, name="add_expense"),
    path("add/", views.smart_add_expense, name="smart_add_expense"),
    path("add-receipt/", views.smart_add_receipt, name="smart_add_receipt"),
    path("edit-expense/<int:expense_id>/", views.edit_expense, name="edit_expense"),
    path("delete-expense/<int:expense_id>/", views.delete_expense, name="delete_expense"),
    path("transactions/", views.all_transactions, name="all_transactions"),
    path("insights/", views.insights, name="insights"),
    path("insights/budget/set/", views.set_category_budget, name="set_category_budget"),
    path("insights/budget/<int:budget_id>/delete/", views.delete_category_budget, name="delete_category_budget"),
    path("chat/", views.finance_chat, name="finance_chat"),
    path("chat/clear/", views.clear_chat, name="clear_chat"),
    path("ai-insights/", views.ai_insights, name="ai_insights"),
    path("forecast/", views.budget_forecast, name="budget_forecast"),
    path("report/", views.monthly_report, name="monthly_report"),
    path("add-income/", views.add_income, name="add_income"),
    path("income/<int:income_id>/edit/", views.edit_income, name="edit_income"),
    path("income/<int:income_id>/delete/", views.delete_income, name="delete_income"),
    path("settings/", views.settings_view, name="settings"),
    path("export/", views.export_csv, name="export_csv"),
    path("import/", views.import_csv, name="import_csv"),
]
