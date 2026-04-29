from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class StaticReporter:
    def __init__(self, template_dir="v2/templates", template="dashboard.j2"):
        self.env = Environment(loader=FileSystemLoader(template_dir))
        self.template = self.env.get_template(template)

    def generate(self, results, output="reports/report.html"):
        html_content = self.template.render(
            strategy_name=results["strategy_name"],
            start_date=results["start_date"],
            end_date=results["end_date"],
            metrics=results["metrics"],
            plot_data_json=results["plot_data_json"],
        )

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return output_path
