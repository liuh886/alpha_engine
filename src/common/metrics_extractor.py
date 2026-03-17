from numbers import Real

class MetricsExtractor:
    """Utility to extract structured JSON metrics from Qlib backtest records."""

    _METRIC_KEYS = ("annualized_return", "information_ratio", "max_drawdown")

    @staticmethod
    def _coerce_metric_dict(payload):
        if not isinstance(payload, dict):
            return {}
        metrics = {}
        for key in MetricsExtractor._METRIC_KEYS:
            value = payload.get(key)
            if value is None:
                continue
            try:
                metrics[key] = float(value)
            except (TypeError, ValueError):
                continue
        return metrics

    @staticmethod
    def _extract_from_analysis_object(analysis):
        if analysis is None:
            return {}
        if isinstance(analysis, tuple):
            for item in analysis:
                metrics = MetricsExtractor._extract_from_analysis_object(item)
                if metrics:
                    return metrics
            return {}
        if isinstance(analysis, list):
            for item in analysis:
                metrics = MetricsExtractor._extract_from_analysis_object(item)
                if metrics:
                    return metrics
            return {}

        metrics = MetricsExtractor._coerce_metric_dict(analysis)
        if metrics:
            return metrics

        attrs = {}
        for key in MetricsExtractor._METRIC_KEYS:
            if hasattr(analysis, key):
                attrs[key] = getattr(analysis, key)
        return MetricsExtractor._coerce_metric_dict(attrs)
    
    @staticmethod
    def extract_from_record(record):
        """
        Extract key performance indicators from a Qlib PortAnaRecord or similar.
        Returns a dictionary of metrics.
        """
        metrics = {}
        try:
            # Attempt to get metrics from record.load_object
            # Qlib usually stores indicators in 'port_analysis.pkl'
            analysis = record.load_object("port_analysis.pkl")
            metrics = MetricsExtractor._extract_from_analysis_object(analysis)
                
            # Try to get from individual records if the above fails
            if not metrics or metrics.get('annualized_return') == 0:
                # Fallback: check other typical Qlib record keys
                for key in ['return', 'risk', 'analysis']:
                    obj = record.load_object(f"{key}.pkl")
                    metrics.update(MetricsExtractor._extract_from_analysis_object(obj))
                                 
            # Final touch: ensure all values are standard Python floats for JSON serialization
            return {k: round(v, 4) if isinstance(v, Real) else v for k, v in metrics.items()}
        except Exception as e:
            print(f"Error extracting metrics: {e}")
            return {"error": str(e)}

    @staticmethod
    def format_summary(metrics, market, start_date, end_date):
        """Format the metrics into a professional summary string or JSON."""
        summary = {
            "market": market.upper(),
            "period": f"{start_date} to {end_date}",
            "performance": metrics,
            "status": "SUCCESS" if "error" not in metrics else "FAILED"
        }
        return summary
